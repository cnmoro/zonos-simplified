// Temporary multi-reference analysis; included inside zs by saved-voices.inc.
struct ReferenceSample {
    std::string id, name;
    std::vector<float> embedding;
    double seconds = 0, preprocessing_ms = 0;
};
struct ReferenceAnalysis {
    std::string id;
    double created_at = 0, expires_at = 0, preprocessing_ms = 0;
    std::vector<ReferenceSample> samples;
};
struct ReferenceAnalysisStore {
    std::mutex mutex, processing;
    std::map<std::string, ReferenceAnalysis> values;
};
static ReferenceAnalysisStore & reference_analysis_store() {
    static ReferenceAnalysisStore store;
    return store;
}
static ReferenceAnalysis find_reference_analysis(const std::string & id) {
    auto & store = reference_analysis_store();
    std::lock_guard<std::mutex> lock(store.mutex);
    auto found = store.values.find(id);
    if (found == store.values.end()) fail(404, "Reference analysis not found; upload the samples again");
    if (found->second.expires_at <= unix_now()) {
        store.values.erase(found);
        fail(410, "Reference analysis expired; upload the samples again");
    }
    return found->second;
}
static std::vector<size_t> reference_selection(const ReferenceAnalysis & analysis, const json & body) {
    if (!body.contains("selected_sample_ids") || !body["selected_sample_ids"].is_array() || body["selected_sample_ids"].empty())
        fail(422, "selected_sample_ids must be a nonempty array");
    std::vector<size_t> result;
    for (const auto & id : body["selected_sample_ids"]) {
        if (!id.is_string()) fail(422, "selected_sample_ids must contain strings");
        auto found = std::find_if(analysis.samples.begin(), analysis.samples.end(), [&](const ReferenceSample & sample) { return sample.id == id.get<std::string>(); });
        if (found == analysis.samples.end()) fail(422, "Selected sample does not belong to this analysis");
        const size_t index = (size_t) (found - analysis.samples.begin());
        if (std::find(result.begin(), result.end(), index) != result.end()) fail(422, "selected_sample_ids must not contain duplicates");
        result.push_back(index);
    }
    // Fixed upload order makes the final float32 mean independent of checkbox/request order.
    std::sort(result.begin(), result.end());
    return result;
}
static std::vector<float> reference_mean(const ReferenceAnalysis & analysis, const std::vector<size_t> & selection) {
    std::vector<std::vector<float>> embeddings;
    for (size_t i : selection) embeddings.push_back(analysis.samples[i].embedding);
    try { return zonos_reference::mean(embeddings); }
    catch (const std::invalid_argument & error) { fail(400, error.what()); }
}
static json reference_report(const ReferenceAnalysis & analysis, const std::vector<size_t> & selection) {
    const auto mean = reference_mean(analysis, selection);
    json samples = json::array(), matrix = json::array(), selected_ids = json::array();
    for (size_t index : selection) selected_ids.push_back(analysis.samples[index].id);
    for (const auto & sample : analysis.samples) {
        samples.push_back({{"id", sample.id}, {"name", sample.name}, {"reference_seconds", sample.seconds},
            {"preprocessing_ms", sample.preprocessing_ms}, {"embedding_norm", zonos_reference::norm(sample.embedding)},
            {"similarity_to_mean", zonos_reference::cosine(sample.embedding, mean)}});
        json row = json::array();
        for (const auto & other : analysis.samples) row.push_back(zonos_reference::cosine(sample.embedding, other.embedding));
        matrix.push_back(std::move(row));
    }
    return {{"id", analysis.id}, {"analysis_id", analysis.id}, {"created_at", analysis.created_at},
        {"expires_at", analysis.expires_at}, {"persistent", false}, {"sample_count", analysis.samples.size()},
        {"preprocessing_ms", analysis.preprocessing_ms}, {"metric", "cosine"}, {"aggregation", "arithmetic_mean"},
        {"interpretation", "Embedding consistency, not a quality score or identity probability"},
        {"selected_sample_ids", selected_ids}, {"samples", samples}, {"pairwise_similarity", matrix}};
}
static std::vector<size_t> all_reference_indices(const ReferenceAnalysis & analysis) {
    std::vector<size_t> result;
    for (size_t i = 0; i < analysis.samples.size(); ++i) result.push_back(i);
    return result;
}
static void create_reference_analysis(ServerState & s, const httplib::Request & request, httplib::Response & response) {
    constexpr size_t mib = 1024 * 1024;
    if (request.body.size() > 96 * mib) fail(413, "Analysis request exceeds 96 MiB");
    auto & store = reference_analysis_store();
    // Avoid concurrent batches duplicating encoder workspace/upload processing.
    std::unique_lock<std::mutex> processing(store.processing, std::try_to_lock);
    if (!processing.owns_lock()) fail(429, "Another reference analysis is processing; retry later");
    {
        std::lock_guard<std::mutex> lock(store.mutex);
        for (auto it = store.values.begin(); it != store.values.end(); )
            if (it->second.expires_at <= unix_now()) it = store.values.erase(it); else ++it;
        if (store.values.size() >= 32) fail(429, "Too many pending analyses; delete an analysis or wait for expiry");
    }
    std::vector<std::string> names;
    json body;
    size_t count = 0, total = 0;
    std::vector<const httplib::MultipartFormData *> parts;
    if (request.is_multipart_form_data()) {
        for (const auto & part : request.files)
            if (part.first != "audio") fail(422, "Only repeated audio multipart fields are accepted");
        for (const auto & part : request.files) parts.push_back(&part.second);
        count = parts.size();
        for (const auto & part : parts) {
            if (part->content.size() > 20 * mib) fail(413, "Each reference must be at most 20 MiB");
            total += part->content.size();
            names.push_back(part->filename);
        }
    } else {
        body = saved_json_body(request);
        saved_validate_fields(body, {"samples"});
        if (!body.contains("samples") || !body["samples"].is_array()) fail(422, "samples must be an array");
        count = body["samples"].size();
        for (const auto & sample : body["samples"]) {
            if (!sample.is_object()) fail(422, "Each sample must be an object");
            saved_validate_fields(sample, {"name", "speaker_audio_base64"});
            if (!sample.contains("name") || !sample["name"].is_string() ||
                !sample.contains("speaker_audio_base64") || !sample["speaker_audio_base64"].is_string())
                fail(422, "Each sample requires name and speaker_audio_base64 strings");
            names.push_back(sample["name"].get<std::string>());
        }
    }
    if (count < 1 || count > 20) fail(422, "Provide between 1 and 20 audio samples");
    if (total > 64 * mib) fail(413, "Combined references exceed 64 MiB");
    for (const auto & name : names)
        if (name.empty() || name.size() > 255 || std::any_of(name.begin(), name.end(), [](unsigned char ch) { return ch < 32 || ch == 127; }))
            fail(422, "Sample names must have 1 to 255 UTF-8 bytes and no control characters");
    // Validate JSON byte limits/base64 before doing any GPU work, one sample at a time.
    if (!request.is_multipart_form_data()) {
        total = 0;
        for (const auto & sample : body["samples"]) {
            auto bytes = decode_b64_field(sample, "speaker_audio_base64");
            if (bytes.size() > 20 * mib) fail(413, "Each reference must be at most 20 MiB");
            total += bytes.size();
            if (total > 64 * mib) fail(413, "Combined references exceed 64 MiB");
        }
    }
    ReferenceAnalysis analysis;
    analysis.id = "analysis_" + random_hex(24);
    const auto started = std::chrono::steady_clock::now();
    for (size_t i = 0; i < count; ++i) {
        const auto sample_started = std::chrono::steady_clock::now();
        std::vector<uint8_t> bytes;
        if (request.is_multipart_form_data()) bytes.assign(parts[i]->content.begin(), parts[i]->content.end());
        else bytes = decode_b64_field(body["samples"][i], "speaker_audio_base64");
        try {
            auto pcm = decode_audio_bytes(bytes);
            ReferenceSample sample;
            sample.id = "sample_" + std::to_string(i + 1);
            sample.name = names[i];
            sample.seconds = (double) pcm.size() / zonos3_generation().sample_rate;
            sample.embedding = embed_audio(s, pcm, reference_seconds());
            const auto norm = zonos_reference::norm(sample.embedding);
            if (!std::isfinite(norm) || norm <= 1e-20) fail(400, "Invalid or zero-norm speaker embedding");
            sample.preprocessing_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - sample_started).count();
            analysis.samples.push_back(std::move(sample));
        } catch (const HttpError & error) {
            fail(error.status, "Failed sample " + std::to_string(i + 1) + ": " + names[i],
                json{{"sample_index", i}, {"sample_name", names[i]}, {"cause", error.body}});
        }
    }
    analysis.preprocessing_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    analysis.created_at = unix_now();
    analysis.expires_at = analysis.created_at + 1800;
    auto report = reference_report(analysis, all_reference_indices(analysis));
    {
        std::lock_guard<std::mutex> lock(store.mutex);
        store.values[analysis.id] = std::move(analysis);
    }
    send_json(response, report, 201);
}
static void register_reference_analysis_routes(httplib::Server & server, ServerState & s) {
    server.Post("/v2/voice-analyses", guarded([&s](const httplib::Request & request, httplib::Response & response) {
        create_reference_analysis(s, request, response);
    }));
    const auto path = R"(/v2/voice-analyses/(analysis_[0-9a-f]{24}))";
    server.Get(path, guarded([](const httplib::Request & request, httplib::Response & response) {
        auto analysis = find_reference_analysis(request.matches[1]);
        send_json(response, reference_report(analysis, all_reference_indices(analysis)));
    }));
    server.Post(R"(/v2/voice-analyses/(analysis_[0-9a-f]{24})/selection)", guarded([](const httplib::Request & request, httplib::Response & response) {
        const auto body = saved_json_body(request);
        saved_validate_fields(body, {"selected_sample_ids"});
        const auto analysis = find_reference_analysis(request.matches[1]);
        send_json(response, reference_report(analysis, reference_selection(analysis, body)));
    }));
    server.Delete(path, guarded([](const httplib::Request & request, httplib::Response & response) {
        auto & store = reference_analysis_store();
        std::lock_guard<std::mutex> lock(store.mutex);
        const auto id = request.matches[1].str();
        if (!store.values.erase(id)) fail(404, "Reference analysis not found");
        send_json(response, json{{"deleted", id}});
    }));
}

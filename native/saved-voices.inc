// Included by speakers.cpp after the encoder helpers, inside namespace zs.
// Persistent named embeddings; no PCM/model copy is kept in this registry.
struct SavedVoiceStore {
    std::mutex mutex;
    fs::path directory;
    std::map<std::string, json> voices;
    SavedVoiceStore() {
        const char * configured = std::getenv("ZONOS3_VOICES_DIR");
        directory = configured && *configured ? configured : "voices";
        fs::create_directories(directory);
        for (const auto & entry : fs::directory_iterator(directory)) {
            if (entry.path().extension() != ".json") continue;
            try {
                std::string raw;
                if (!read_file(entry.path(), raw)) throw std::runtime_error("unreadable file");
                auto voice = json::parse(raw);
                const auto id = voice.at("id").get<std::string>();
                if (!std::regex_match(id, std::regex("voice_[0-9a-f]{24}")) || entry.path().stem() != id ||
                    voice.at("model") != "ZONOS3-Mini/ownmect_s2" || voice.at("version") != 1 ||
                    !voice.at("name").is_string() || !voice.at("embedding").is_array() || voice.at("embedding").size() != 192)
                    throw std::runtime_error("invalid voice record or encoder version");
                for (const auto & value : voice.at("embedding"))
                    if (!value.is_number() || !std::isfinite(value.get<float>())) throw std::runtime_error("invalid embedding");
                voices[id] = std::move(voice);
            } catch (const std::exception & error) {
                fprintf(stderr, "saved voices: cannot load %s: %s\n", entry.path().c_str(), error.what());
            }
        }
    }
    void write(const json & voice) {
        const auto target = directory / (voice.at("id").get<std::string>() + ".json");
        const auto temporary = directory / (".tmp-" + random_hex(24));
        const auto body = voice.dump(2) + "\n";
        FILE * file = fopen(temporary.c_str(), "wb");
        if (!file) fail(500, "Cannot write persistent voice storage");
        bool ok = fwrite(body.data(), 1, body.size(), file) == body.size();
        ok = fflush(file) == 0 && ok;
#ifndef _WIN32
        ok = fsync(fileno(file)) == 0 && ok;
#endif
        ok = fclose(file) == 0 && ok;
        std::error_code ec;
        if (ok) fs::rename(temporary, target, ec);
        if (!ok || ec) {
            fs::remove(temporary);
            fail(500, "Cannot commit persistent voice storage");
        }
    }
};

static SavedVoiceStore & saved_voice_store() {
    static SavedVoiceStore store;
    return store;
}

static json saved_voice_public(json voice) {
    voice.erase("embedding");
    voice.erase("version");
    voice["speaker_embedding_id"] = voice.at("id");
    voice["ready"] = true;
    voice["persistent"] = true;
    voice["speaker_modes"] = json::array({"embedding"});
    voice["embedding_dim"] = 192;
    return voice;
}

static std::optional<Speaker> lookup_saved_voice(const std::string & id) {
    auto & store = saved_voice_store();
    std::lock_guard<std::mutex> lock(store.mutex);
    auto found = store.voices.find(id);
    if (found == store.voices.end()) return std::nullopt;
    const auto & value = found->second;
    Speaker speaker;
    speaker.id = id;
    speaker.label = value.at("name").get<std::string>();
    speaker.source_type = "embedding";
    speaker.is_default = true; // Native global lookup semantics; no session or encoder is needed.
    speaker.created = value.at("created_at").get<double>();
    speaker.embedding = value.at("embedding").get<std::vector<float>>();
    return speaker;
}

static json list_saved_voices() {
    auto & store = saved_voice_store();
    std::lock_guard<std::mutex> lock(store.mutex);
    json voices = json::array();
    for (const auto & pair : store.voices) voices.push_back(saved_voice_public(pair.second));
    return voices;
}

static json saved_json_body(const httplib::Request & request) {
    const auto body = json::parse(request.body, nullptr, false);
    if (body.is_discarded() || !body.is_object()) fail(422, "Expected a JSON object");
    return body;
}

static void saved_validate_fields(const json & body, const std::vector<std::string> & fields) {
    for (auto item = body.begin(); item != body.end(); ++item)
        if (std::find(fields.begin(), fields.end(), item.key()) == fields.end()) fail(422, "Unknown field: " + item.key());
}

static std::string saved_name(const json & body) {
    if (!body.contains("name") || !body["name"].is_string()) fail(422, "name must be a string");
    auto name = strip(body["name"].get<std::string>());
    if (name.empty() || name.size() > 120 || std::any_of(name.begin(), name.end(), [](unsigned char ch) { return ch < 32 || ch == 127; }))
        fail(422, "name must have 1 to 120 UTF-8 bytes and no control characters");
    return name;
}

static std::string saved_language(const json & body) {
    if (!body.contains("language")) return "pt_br";
    if (!body["language"].is_string()) fail(422, "language must be pt_br or en_us");
    auto language = body["language"].get<std::string>();
    if (language != "pt_br" && language != "en_us") fail(422, "language must be pt_br or en_us");
    return language;
}

// Call with store.mutex held, both before expensive preprocessing and before commit.
static void saved_unique_name(const SavedVoiceStore & store, const std::string & name, const std::string & except = "") {
    for (const auto & pair : store.voices)
        if (pair.first != except && lower_ascii(pair.second.at("name").get<std::string>()) == lower_ascii(name))
            fail(409, "A saved voice with this name already exists", json{{"voice_id", pair.first}});
}

#include "reference-analysis.inc"

static void saved_create(ServerState & s, const httplib::Request & request, httplib::Response & response) {
    constexpr size_t max_audio = 20 * 1024 * 1024;
    if (request.body.size() > 28 * 1024 * 1024) fail(413, "Request exceeds 28 MiB");
    json body;
    std::vector<uint8_t> audio;
    if (request.is_multipart_form_data()) {
        body = json::object();
        for (const auto & part : request.files) {
            if (part.first != "audio" && part.first != "name" && part.first != "language") fail(422, "Unknown multipart field: " + part.first);
            if (request.get_file_values(part.first).size() != 1) fail(422, "Multipart fields must not be repeated");
        }
        for (const auto * field : {"name", "language"})
            if (request.has_file(field)) body[field] = request.get_file_value(field).content;
        if (!request.has_file("audio")) fail(422, "audio is required");
        const auto part = request.get_file_value("audio");
        audio.assign(part.content.begin(), part.content.end());
    } else {
        body = saved_json_body(request);
        saved_validate_fields(body, {"name", "language", "speaker_audio_base64", "speaker_audio_name", "speaker_embedding_id", "analysis_id", "selected_sample_ids", "confirmed"});
        const bool has_audio = body.contains("speaker_audio_base64");
        const bool has_id = body.contains("speaker_embedding_id");
        const bool has_analysis = body.contains("analysis_id");
        if ((int) has_audio + (int) has_id + (int) has_analysis != 1)
            fail(422, "Provide exactly one of speaker_audio_base64, speaker_embedding_id or analysis_id");
        if (has_analysis) {
            if (!body["analysis_id"].is_string()) fail(422, "analysis_id must be a string");
            if (!body.contains("confirmed") || !body["confirmed"].is_boolean() || !body["confirmed"].get<bool>())
                fail(422, "Explicit confirmation is required: confirmed must be true");
        } else if (body.contains("selected_sample_ids") || body.contains("confirmed")) {
            fail(422, "selected_sample_ids and confirmed require analysis_id");
        }
        if (has_audio) {
            if (!body["speaker_audio_base64"].is_string()) fail(422, "speaker_audio_base64 must be a string");
            audio = decode_b64_field(body, "speaker_audio_base64");
        } else if (has_id && (!body["speaker_embedding_id"].is_string() || body["speaker_embedding_id"].get<std::string>().empty())) {
            fail(422, "speaker_embedding_id must be a nonempty string");
        }
    }
    const auto name = saved_name(body), language = saved_language(body);
    if (audio.size() > max_audio) fail(413, "Audio exceeds 20 MiB");
    if (!body.contains("speaker_embedding_id") && !body.contains("analysis_id") && audio.empty()) fail(400, "Audio is empty");
    auto & store = saved_voice_store();
    {
        std::lock_guard<std::mutex> lock(store.mutex);
        saved_unique_name(store, name);
    }
    const auto started = std::chrono::steady_clock::now();
    std::vector<float> embedding;
    double reference_duration = 0;
    std::optional<ReferenceAnalysis> analysis;
    std::vector<size_t> selected;
    if (body.contains("analysis_id")) {
        analysis = find_reference_analysis(body["analysis_id"].get<std::string>());
        selected = reference_selection(*analysis, body);
        embedding = reference_mean(*analysis, selected);
        for (size_t index : selected) reference_duration += analysis->samples[index].seconds;
    } else if (body.contains("speaker_embedding_id")) {
        embedding = voice_embedding(s, session_id(request), body["speaker_embedding_id"].get<std::string>());
    } else {
        auto pcm = decode_audio_bytes(audio);
        reference_duration = (double) pcm.size() / zonos3_generation().sample_rate;
        embedding = embed_audio(s, pcm, reference_seconds());
    }
    json voice = {{"version", 1}, {"id", "voice_" + random_hex(24)}, {"name", name},
        {"language", language}, {"model", "ZONOS3-Mini/ownmect_s2"}, {"created_at", unix_now()},
        {"embedding", embedding}, {"reference_seconds", reference_duration},
        {"preprocessing_ms", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count()}};
    if (analysis) {
        json selected_ids = json::array(), sources = json::array();
        for (size_t index : selected) {
            const auto & sample = analysis->samples[index];
            selected_ids.push_back(sample.id);
            sources.push_back({{"id", sample.id}, {"name", sample.name}, {"reference_seconds", sample.seconds},
                {"similarity_to_profile", zonos_reference::cosine(sample.embedding, embedding)}});
        }
        voice["sample_count"] = selected.size();
        voice["preprocessing_ms"] = analysis->preprocessing_ms;
        voice["reference_analysis"] = {{"aggregation", "arithmetic_mean"}, {"selected_sample_ids", selected_ids}, {"samples", sources}};
    }
    {
        std::lock_guard<std::mutex> lock(store.mutex);
        saved_unique_name(store, name);
        store.write(voice); // Compute + disk commit finish before reporting ready.
        store.voices[voice["id"].get<std::string>()] = voice;
    }
    send_json(response, saved_voice_public(voice), 201);
}

static void register_saved_voice_routes(httplib::Server & server, ServerState & s) {
    // Fail startup if the configured persistent directory cannot be initialized.
    saved_voice_store();
    register_reference_analysis_routes(server, s);
    server.Get("/v2/voices", guarded([](const httplib::Request &, httplib::Response & response) {
        send_json(response, json{{"voices", list_saved_voices()}});
    }));
    server.Post("/v2/voices", guarded([&s](const httplib::Request & request, httplib::Response & response) {
        saved_create(s, request, response);
    }));
    const auto path = R"(/v2/voices/(voice_[0-9a-f]{24}))";
    server.Get(path, guarded([](const httplib::Request & request, httplib::Response & response) {
        auto & store = saved_voice_store();
        std::lock_guard<std::mutex> lock(store.mutex);
        const auto found = store.voices.find(request.matches[1]);
        if (found == store.voices.end()) fail(404, "Saved voice not found");
        send_json(response, saved_voice_public(found->second));
    }));
    server.Patch(path, guarded([](const httplib::Request & request, httplib::Response & response) {
        auto body = saved_json_body(request);
        saved_validate_fields(body, {"name", "language"});
        if (body.empty()) fail(422, "Provide name or language");
        auto & store = saved_voice_store();
        std::lock_guard<std::mutex> lock(store.mutex);
        const auto found = store.voices.find(request.matches[1]);
        if (found == store.voices.end()) fail(404, "Saved voice not found");
        auto voice = found->second;
        if (body.contains("name")) {
            voice["name"] = saved_name(body);
            saved_unique_name(store, voice["name"].get<std::string>(), found->first);
        }
        if (body.contains("language")) voice["language"] = saved_language(body);
        store.write(voice);
        found->second = voice;
        send_json(response, saved_voice_public(voice));
    }));
    server.Delete(path, guarded([](const httplib::Request & request, httplib::Response & response) {
        auto & store = saved_voice_store();
        std::lock_guard<std::mutex> lock(store.mutex);
        const auto found = store.voices.find(request.matches[1]);
        if (found == store.voices.end()) fail(404, "Saved voice not found");
        if (!fs::remove(store.directory / (found->first + ".json"))) fail(500, "Could not delete saved voice file");
        const auto id = found->first;
        store.voices.erase(found);
        send_json(response, json{{"deleted", id}});
    }));
}

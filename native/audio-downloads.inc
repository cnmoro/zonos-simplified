// Native, bounded disk cache for pitch-preserving WAV speed variants. Included inside zs.
struct DownloadWaveInfo {
    uint64_t frames = 0;
    double seconds() const { return (double) frames / 44100; }
};
static DownloadWaveInfo download_wave_info(const fs::path & path) {
    std::ifstream input(path, std::ios::binary);
    char header[12]; input.read(header, 12);
    if (!input || std::memcmp(header,"RIFF",4) || std::memcmp(header+8,"WAVE",4)) throw std::runtime_error("Not a WAV file");
    bool format_ok = false; uint32_t data_bytes = 0;
    const auto size = fs::file_size(path);
    while (input && (uint64_t) input.tellg() + 8 <= size) {
        uint8_t chunk[8]; input.read((char *) chunk, 8);
        const uint32_t length = le32(chunk+4);
        const auto start = (uint64_t) input.tellg();
        if (start + length > size) throw std::runtime_error("Truncated WAV");
        if (!std::memcmp(chunk,"fmt ",4) && length >= 16) {
            uint8_t format[16]; input.read((char *) format,16);
            format_ok = le16(format)==1 && le16(format+2)==1 && le32(format+4)==44100 && le16(format+12)==2 && le16(format+14)==16;
        } else if (!std::memcmp(chunk,"data",4)) data_bytes = length;
        input.seekg((std::streamoff) (start+length+(length%2)));
    }
    if (!format_ok || !data_bytes || data_bytes%2) throw std::runtime_error("Expected nonempty PCM16 mono WAV at 44100 Hz");
    return {data_bytes/2};
}
struct DownloadVariant { fs::path path; double duration = 0; };
struct DownloadAsset {
    std::string id, name;
    fs::path directory;
    double created_at = 0, expires_at = 0, duration = 0;
    std::mutex mutex;
    std::map<int,DownloadVariant> variants;
    ~DownloadAsset() { std::error_code error; fs::remove_all(directory,error); }
};
struct DownloadStore {
    std::mutex mutex, processing;
    fs::path directory;
    std::map<std::string,std::shared_ptr<DownloadAsset>> assets;
    DownloadStore() {
        const char * configured = std::getenv("ZONOS3_AUDIO_CACHE_DIR");
        const fs::path root = configured && *configured ? configured : "outputs/audio-cache";
        fs::create_directories(root); fs::permissions(root,fs::perms::owner_all,fs::perm_options::replace);
#ifdef _WIN32
        const int pid = _getpid();
#else
        const int pid = getpid();
        // Remove cache directories belonging to terminated server processes, never live instances.
        for (const auto & entry : fs::directory_iterator(root)) {
            std::smatch match; const auto name = entry.path().filename().string();
            if (!std::regex_match(name,match,std::regex("instance_([0-9]{1,10})"))) continue;
            const auto owner = std::stoll(match[1]);
            if (owner < 1 || owner > 2147483647) continue;
            errno = 0;
            if (owner == pid || (kill((int) owner,0) != 0 && errno == ESRCH)) {
                std::error_code error; fs::remove_all(entry.path(),error);
            }
        }
#endif
        directory = root / ("instance_" + std::to_string(pid)); fs::create_directories(directory);
    }
    void prune_locked() {
        for (auto it=assets.begin();it!=assets.end();)
            if (it->second->expires_at <= unix_now()) it=assets.erase(it); else ++it;
    }
    void reserve_disk(uint64_t requested) {
        uint64_t used=0;
        std::error_code error;
        fs::recursive_directory_iterator it(directory,fs::directory_options::skip_permission_denied,error), end;
        while (it!=end) {
            const auto & entry=*it;
            if (entry.is_regular_file(error)) { const auto size=entry.file_size(error); if(!error) used+=size; }
            error.clear(); it.increment(error);
        }
        if (used+requested > 512ull*1024*1024) fail(507,"Audio download cache is full; delete old audio assets or wait for expiry");
    }
};
static DownloadStore & download_store() { static DownloadStore store; return store; }
static std::string download_speed_text(int speed) { return std::to_string(speed/10)+"."+std::to_string(speed%10); }
static int download_speed(const std::string & raw) {
    if (raw.empty() || raw.size()>16) fail(422,"speed must be 0.5..2.0 in steps of 0.1");
    char * end=nullptr; const double value=std::strtod(raw.c_str(),&end);
    if (end!=raw.c_str()+raw.size() || !std::isfinite(value) || value<.5 || value>2 || std::abs(value*10-std::round(value*10))>1e-8)
        fail(422,"speed must be 0.5..2.0 in steps of 0.1");
    return (int) std::round(value*10);
}
static void download_query_fields(const httplib::Request & request,const std::string & allowed) {
    for (const auto & field:request.params)
        if (field.first!=allowed || request.get_param_value_count(allowed)>1) fail(422,"Unknown or repeated query parameter");
}
static std::shared_ptr<DownloadAsset> find_download_asset(const std::string & id) {
    auto & store=download_store(); std::lock_guard<std::mutex> lock(store.mutex);
    const auto found=store.assets.find(id);
    if (found==store.assets.end()) fail(404,"Audio asset not found; upload the audio again");
    if (found->second->expires_at <= unix_now()) { store.assets.erase(found); fail(410,"Audio asset expired; upload the audio again"); }
    return found->second;
}
static json download_asset_json(const DownloadAsset & asset) {
    return {{"id",asset.id},{"name",asset.name},{"duration_seconds",asset.duration},{"expires_at",asset.expires_at},
        {"persistent",false},{"format","wav"},{"sample_rate",44100},{"channels",1},
        {"speed_min",.5},{"speed_max",2.0},{"speed_step",.1},
        {"durations_url","/v2/audio-assets/"+asset.id+"/durations"},
        {"download_url","/v2/audio-assets/"+asset.id+"/download?speed=1.0"}};
}
static DownloadVariant download_variant(const std::shared_ptr<DownloadAsset> & asset,int speed) {
    std::lock_guard<std::mutex> lock(asset->mutex);
    if (asset->variants.count(speed)) return asset->variants.at(speed);
    auto & store=download_store(); std::lock_guard<std::mutex> processing(store.processing);
    store.reserve_disk((uint64_t)(asset->duration / (speed/10.0)*88200*1.05)+4096);
    const auto target=asset->directory/("speed-"+std::to_string(speed)+".wav");
    const auto temporary=asset->directory/(".speed-"+std::to_string(speed)+".wav");
    std::string error;
    const int result=run_process({audio_ffmpeg_path().string(),"-nostdin","-hide_banner","-loglevel","error","-y",
        "-threads","1","-filter_threads","1","-i",asset->variants.at(10).path.string(),
        "-map_metadata","-1","-vn","-af","atempo="+download_speed_text(speed),"-ar","44100","-ac","1","-c:a","pcm_s16le",temporary.string()},error);
    if (result!=0) { fs::remove(temporary); fail(500,"Audio speed conversion failed"); }
    try {
        const auto info=download_wave_info(temporary);
        fs::rename(temporary,target);
        DownloadVariant variant{target,info.seconds()}; asset->variants[speed]=variant; return variant;
    } catch (const std::exception &) { fs::remove(temporary); fail(500,"Invalid audio returned by speed conversion"); }
}
static void create_download_asset(const httplib::Request & request,httplib::Response & response) {
    if (request.body.size()>28*1024*1024) fail(413,"Audio asset request exceeds 28 MiB");
    std::vector<uint8_t> bytes; std::string name="audio.wav";
    if (request.is_multipart_form_data()) {
        if (request.files.size()!=1 || !request.has_file("audio")) fail(422,"Provide exactly one audio multipart field");
        const auto part=request.get_file_value("audio"); name=part.filename; bytes.assign(part.content.begin(),part.content.end());
    } else {
        const auto body=saved_json_body(request); saved_validate_fields(body,{"audio_base64","audio_name"});
        if (!body.contains("audio_base64") || !body["audio_base64"].is_string()) fail(422,"audio_base64 must be a string");
        if (body.contains("audio_name")) { if (!body["audio_name"].is_string()) fail(422,"audio_name must be a string"); name=body["audio_name"].get<std::string>(); }
        bytes=decode_b64_field(body,"audio_base64");
    }
    if (bytes.empty()) fail(400,"Audio is empty");
    if (bytes.size()>20*1024*1024) fail(413,"Audio exceeds 20 MiB");
    if (name.empty() || name.size()>255 || std::any_of(name.begin(),name.end(),[](unsigned char c){return c<32 || c==127;})) fail(422,"Invalid audio filename");
    auto & store=download_store();
    std::lock_guard<std::mutex> processing(store.processing);
    {
        std::lock_guard<std::mutex> lock(store.mutex); store.prune_locked();
        if (store.assets.size()>=32) fail(429,"Too many audio assets; delete an old one or wait for expiry");
    }
    store.reserve_disk(bytes.size()+22ull*1024*1024);
    auto asset=std::make_shared<DownloadAsset>(); asset->id="audio_"+random_hex(24); asset->name=name;
    asset->directory=store.directory/asset->id; fs::create_directories(asset->directory);
    const auto input=asset->directory/"input.bin", original=asset->directory/"speed-10.wav";
    FILE * file=fopen(input.c_str(),"wb"); if (!file) fail(500,"Cannot write audio cache");
    const bool written=fwrite(bytes.data(),1,bytes.size(),file)==bytes.size(); const int closed=fclose(file);
    if (!written || closed!=0) fail(500,"Cannot write audio cache");
    bool canonical=false; DownloadWaveInfo info;
    try { info=download_wave_info(input); canonical=true; } catch (const std::exception &) {}
    if (canonical) {
        if (info.seconds()>120) fail(413,"Audio must be at most 120 seconds");
        fs::rename(input,original);
    } else {
        auto pcm=audio_decode_file(input.c_str(),44100,121);
        if (pcm.empty()) fail(400,"Audio cannot be decoded");
        if (pcm.size()>120ull*44100) fail(413,"Audio must be at most 120 seconds");
        if (!wav_pcm16_write(original.c_str(),pcm,44100)) fail(500,"Cannot normalize audio");
        info=download_wave_info(original); fs::remove(input);
    }
    asset->duration=info.seconds(); asset->created_at=unix_now(); asset->expires_at=asset->created_at+3600;
    asset->variants[10]={original,asset->duration};
    { std::lock_guard<std::mutex> lock(store.mutex); store.assets[asset->id]=asset; }
    send_json(response,download_asset_json(*asset),201);
}
static void register_download_routes(httplib::Server & server) {
    download_store();
    server.Post("/v2/audio-assets",guarded(create_download_asset));
    const auto path=R"(/v2/audio-assets/(audio_[0-9a-f]{24}))";
    server.Get(path,guarded([](const httplib::Request & request,httplib::Response & response){
        const auto asset=find_download_asset(request.matches[1]); send_json(response,download_asset_json(*asset));
    }));
    server.Get(R"(/v2/audio-assets/(audio_[0-9a-f]{24})/durations)",guarded([](const httplib::Request & request,httplib::Response & response){
        download_query_fields(request,"speeds"); const auto asset=find_download_asset(request.matches[1]);
        std::vector<int> speeds;
        if (!request.has_param("speeds")) { for (int i=5;i<=20;++i) speeds.push_back(i); }
        else {
            std::string raw=request.get_param_value("speeds"); if(raw.empty() || raw.size()>256) fail(422,"Invalid speeds list");
            size_t start=0;
            while (start<=raw.size()) {
                const auto end=raw.find(',',start); const auto token=raw.substr(start,end==std::string::npos ? std::string::npos : end-start);
                const int speed=download_speed(token);
                if (std::find(speeds.begin(),speeds.end(),speed)!=speeds.end()) fail(422,"speeds must not repeat values");
                speeds.push_back(speed); if (end==std::string::npos) break; start=end+1;
            }
        }
        json variants=json::array();
        for (int speed:speeds) {
            const auto variant=download_variant(asset,speed);
            variants.push_back({{"speed",speed/10.0},{"duration_seconds",variant.duration},
                {"download_url","/v2/audio-assets/"+asset->id+"/download?speed="+download_speed_text(speed)}});
        }
        send_json(response,{{"id",asset->id},{"original_duration_seconds",asset->duration},{"expires_at",asset->expires_at},
            {"duration_is_measured",true},{"preserves_pitch",true},{"variants",variants}});
    }));
    server.Get(R"(/v2/audio-assets/(audio_[0-9a-f]{24})/download)",guarded([](const httplib::Request & request,httplib::Response & response){
        download_query_fields(request,"speed"); const auto asset=find_download_asset(request.matches[1]);
        const int speed=request.has_param("speed") ? download_speed(request.get_param_value("speed")) : 10;
        const auto variant=download_variant(asset,speed);
        auto file=std::make_shared<std::ifstream>(variant.path,std::ios::binary);
        if (!*file) fail(500,"Audio variant file unavailable");
        response.set_header("Content-Disposition","attachment; filename=\"zonos-"+asset->id+"-"+download_speed_text(speed)+"x.wav\"");
        response.set_header("X-Audio-Duration-Seconds",std::to_string(variant.duration));
        response.set_header("X-Audio-Speed",download_speed_text(speed)); response.set_header("Cache-Control","no-store");
        response.set_content_provider(fs::file_size(variant.path),"audio/wav",[file,asset](size_t offset,size_t length,httplib::DataSink & sink){
            std::array<char,65536> buffer; const size_t count=std::min(length,buffer.size());
            file->seekg((std::streamoff)offset); file->read(buffer.data(),(std::streamsize)count);
            return file->gcount()==(std::streamsize)count && sink.write(buffer.data(),count);
        });
    }));
    server.Delete(path,guarded([](const httplib::Request & request,httplib::Response & response){
        auto & store=download_store(); std::lock_guard<std::mutex> lock(store.mutex);
        const auto id=request.matches[1].str(); if(!store.assets.erase(id)) fail(404,"Audio asset not found");
        send_json(response,{{"deleted",id}});
    }));
}

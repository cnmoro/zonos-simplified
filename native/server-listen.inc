// Select the primary listener. HTTPS-only does not bind any plain HTTP socket.
const char * http_disabled_env = std::getenv("ZONOS3_HTTP_DISABLED");
const bool http_disabled = http_disabled_env && std::string(http_disabled_env) == "1";
if (http_disabled && !tls_server) {
    fprintf(stderr, "error: HTTPS-only requires TLS certificate and key\n");
    stop_scheduler(s); stop_reference_reaper(s); return 1;
}
bool bound = !s.worker_failed;
if (bound && !http_disabled) {
    if (port == 0) {
        port = svr.bind_to_any_port(host);
        bound = port > 0;
    } else bound = svr.bind_to_port(host, port);
}
bool ok = false;
if (bound) {
    if (!http_disabled)
        fprintf(stderr, "zonos3-server: listening on http://%s:%d (studio: %s)\n", host.c_str(), port, s.studio_dir.c_str());
    if (tls_server)
        fprintf(stderr, "zonos3-server: listening on https://%s:%d (shared engine, HTTP %s)\n", host.c_str(), tls_port, http_disabled ? "disabled" : "enabled");
    if (ctl) {
        ctl->svr = http_disabled ? tls_server.get() : &svr;
        ctl->port.store(http_disabled ? tls_port : port);
    }
    if (tls_server && !http_disabled) {
        tls_thread = std::thread([&] {
            if (!tls_server->listen_after_bind()) { fprintf(stderr, "error: HTTPS accept loop failed\n"); svr.stop(); }
        });
    }
    ok = http_disabled ? tls_server->listen_after_bind() : svr.listen_after_bind();
}

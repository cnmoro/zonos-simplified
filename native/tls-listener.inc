// Included in server_run after both the engine and route-registration lambda exist.
std::unique_ptr<httplib::SSLServer> tls_server;
std::thread tls_thread;
int tls_port = 1920;
const char * tls_cert = std::getenv("ZONOS3_TLS_CERT");
const char * tls_key = std::getenv("ZONOS3_TLS_KEY");
if ((tls_cert && *tls_cert) || (tls_key && *tls_key)) {
    if (!tls_cert || !*tls_cert || !tls_key || !*tls_key ||
        !env_int("ZONOS3_TLS_PORT", 1920, tls_port) || tls_port < 1 || tls_port > 65535 || tls_port == port) {
        fprintf(stderr, "error: configure TLS certificate, key and a separate valid ZONOS3_TLS_PORT\n");
        stop_scheduler(s); stop_reference_reaper(s); return 1;
    }
    tls_server = std::make_unique<httplib::SSLServer>(tls_cert, tls_key);
    if (!tls_server->is_valid()) {
        fprintf(stderr, "error: TLS certificate/key could not be loaded\n");
        stop_scheduler(s); stop_reference_reaper(s); return 1;
    }
    register_local_routes(*tls_server);
    if (!tls_server->bind_to_port(host, tls_port)) {
        fprintf(stderr, "error: cannot bind HTTPS %s:%d\n", host.c_str(), tls_port);
        stop_scheduler(s); stop_reference_reaper(s); return 1;
    }
}

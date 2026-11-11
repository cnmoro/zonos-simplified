#!/usr/bin/env python3
"""Apply the local native named-voice extension, reproducibly and idempotently."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/ZONOS3-Mini/servers/ggml/src/server'


def patch():
    path = SOURCE / 'speakers.cpp'
    text = path.read_text()
    if '// ZONOS_LOCAL_SAVED_VOICES' not in text:
        replacements = [
            ('#include <filesystem>', '#include <filesystem>\n#include <regex>'),
            ('// ------------------------------------------------------------------------------------------------ voice lookup',
             '// ZONOS_LOCAL_SAVED_VOICES\nstatic std::vector<float> voice_embedding(ServerState &, const std::optional<std::string> &, const std::string &);\n#include "saved-voices.inc"\n\n// ------------------------------------------------------------------------------------------------ voice lookup'),
            ('static Speaker lookup_voice(ServerState & s, const std::optional<std::string> & session, const std::string & id) {',
             'static Speaker lookup_voice(ServerState & s, const std::optional<std::string> & session, const std::string & id) {\n    if (auto saved = lookup_saved_voice(id)) return *saved;'),
            ('bool speaker_known(ServerState & s, const std::optional<std::string> & session, const std::string & id) {',
             'bool speaker_known(ServerState & s, const std::optional<std::string> & session, const std::string & id) {\n    if (lookup_saved_voice(id)) return true;'),
            ('    send_json(res, json{{"speakers", arr}});',
             '    for (const auto & saved : list_saved_voices()) {\n        if (auto speaker = lookup_saved_voice(saved["id"].get<std::string>())) {\n            auto item = speaker_json(s, *speaker);\n            item["persistent"] = true;\n            item["ready"] = true;\n            item["language"] = saved["language"];\n            arr.push_back(item);\n        }\n    }\n    send_json(res, json{{"speakers", arr}});'),
            ('void register_speaker_routes(httplib::Server & svr, ServerState & s) {',
             'void register_speaker_routes(httplib::Server & svr, ServerState & s) {\n    register_saved_voice_routes(svr, s);'),
        ]
        for old, new in replacements:
            if text.count(old) != 1:
                raise RuntimeError(f'Runtime changed: expected one patch anchor: {old}')
            text = text.replace(old, new)
        path.write_text(text)
    for name in ('saved-voices.inc', 'reference-analysis.inc', 'reference-math.h', 'tls-listener.inc', 'server-listen.inc'):
        shutil.copyfile(ROOT / 'native' / name, SOURCE / name)
    text = path.read_text()
    if '#include "reference-math.h"' not in text:
        text = text.replace('#include <regex>', '#include <regex>\n#include "reference-math.h"')
        path.write_text(text)
    path = SOURCE / 'main.cpp'
    text = path.read_text()
    if '// ZONOS_LOCAL_TLS_LISTENER' not in text:
        start = text.index('    install_middleware(svr);')
        end = text.index('\n\n    fprintf(stderr, "zonos3-server: backbone=', start)
        routes = text[start:end].replace('(svr,', '(endpoint,').replace('(svr)', '(endpoint)')
        routes = '    endpoint.set_read_timeout(120);\n    endpoint.set_write_timeout(600);\n' + routes
        text = text[:start] + ('    // ZONOS_LOCAL_TLS_LISTENER\n'
            '    auto register_local_routes = [&](httplib::Server & endpoint) {\n' + routes + '\n    };\n'
            '    register_local_routes(svr);\n#include "tls-listener.inc"') + text[end:]
        anchor = '        ok = svr.listen_after_bind();'
        assert text.count(anchor) == 1
        text = text.replace(anchor, '        if (tls_server) {\n'
            '            fprintf(stderr, "zonos3-server: listening on https://%s:%d (shared engine)\\n", host.c_str(), tls_port);\n'
            '            tls_thread = std::thread([&] {\n'
            '                if (!tls_server->listen_after_bind()) { fprintf(stderr, "error: HTTPS accept loop failed\\n"); svr.stop(); }\n'
            '            });\n        }\n' + anchor)
        anchor = '    if (s.pyhost) s.pyhost->close();'
        assert text.count(anchor) == 1
        text = text.replace(anchor, '    if (tls_server) tls_server->stop();\n'
            '    if (tls_thread.joinable()) tls_thread.join();\n\n' + anchor)
        path.write_text(text)
    text = path.read_text()
    target = 'auto register_local_routes = [&](httplib::Server & endpoint) {'
    if 'endpoint.set_read_timeout(120);' not in text:
        text = text.replace(target, target + '\n    endpoint.set_read_timeout(120);\n    endpoint.set_write_timeout(600);')
        path.write_text(text)
    text = path.read_text()
    if '#include "server-listen.inc"' not in text:
        start = text.index('    bool bound = !s.worker_failed;')
        end = text.index('    if (tls_server) tls_server->stop();', start)
        text = text[:start] + '#include "server-listen.inc"\n\n' + text[end:]
        path.write_text(text)
    cmake = SOURCE.parents[1] / 'CMakeLists.txt'
    text = cmake.read_text()
    if '# ZONOS_LOCAL_TLS' not in text:
        text += ('\n# ZONOS_LOCAL_TLS: one engine, native HTTP and HTTPS listeners.\n'
            'find_package(OpenSSL REQUIRED)\n'
            'target_compile_definitions(zonos3-server-core PUBLIC CPPHTTPLIB_OPENSSL_SUPPORT)\n'
            'target_link_libraries(zonos3-server-core PUBLIC OpenSSL::SSL OpenSSL::Crypto)\n')
        cmake.write_text(text)
    path = SOURCE / 'http.cpp'
    text = path.read_text()
    anchor = 'void install_middleware(httplib::Server & svr) {'
    if 'svr.set_payload_max_length(96 * 1024 * 1024);' not in text:
        if anchor not in text:
            raise RuntimeError('Runtime changed: middleware patch anchor is missing')
        text = text.replace(anchor, anchor + '\n    svr.set_payload_max_length(96 * 1024 * 1024);')
    old = 'res.set_content(body, httplib::detail::find_content_type(target.string(), {}, "application/octet-stream"));'
    if old in text:
        text = text.replace(old, 'res.set_content(body, rel_path == "agents.md" ? "text/markdown; charset=utf-8" : httplib::detail::find_content_type(target.string(), {}, "application/octet-stream"));')
    path.write_text(text)


if __name__ == '__main__':
    patch()

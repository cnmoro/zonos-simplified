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
    shutil.copyfile(ROOT / 'native/saved-voices.inc', SOURCE / 'saved-voices.inc')
    path = SOURCE / 'http.cpp'
    text = path.read_text()
    old = 'res.set_content(body, httplib::detail::find_content_type(target.string(), {}, "application/octet-stream"));'
    if old in text:
        text = text.replace(old, 'res.set_content(body, rel_path == "agents.md" ? "text/markdown; charset=utf-8" : httplib::detail::find_content_type(target.string(), {}, "application/octet-stream"));')
        path.write_text(text)


if __name__ == '__main__':
    patch()

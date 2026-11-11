#pragma once
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace zonos_reference {
inline double norm(const std::vector<float> & value) {
    double sum = 0;
    for (float x : value) sum += (double) x * x;
    return std::sqrt(sum);
}
inline double cosine(const std::vector<float> & a, const std::vector<float> & b) {
    if (a.size() != b.size() || a.empty()) throw std::invalid_argument("Embedding dimensions differ");
    const double denominator = norm(a) * norm(b);
    if (!std::isfinite(denominator) || denominator <= 1e-20) throw std::invalid_argument("Embedding has zero or invalid norm");
    double dot = 0;
    for (size_t i = 0; i < a.size(); ++i) dot += (double) a[i] * b[i];
    return std::clamp(dot / denominator, -1.0, 1.0);
}
inline std::vector<float> mean(const std::vector<std::vector<float>> & values) {
    if (values.empty() || values.front().empty()) throw std::invalid_argument("No embeddings selected");
    std::vector<float> result(values.front().size(), 0);
    for (const auto & value : values) {
        if (value.size() != result.size()) throw std::invalid_argument("Embedding dimensions differ");
        for (size_t i = 0; i < value.size(); ++i) result[i] += value[i];
    }
    for (float & x : result) x /= (float) values.size();
    if (norm(result) <= 1e-20) throw std::invalid_argument("Selected embeddings cancel each other");
    return result;
}
} // namespace zonos_reference

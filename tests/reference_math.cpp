#include "../native/reference-math.h"
#include <cassert>
#include <iostream>

int main() {
    using namespace zonos_reference;
    const std::vector<float> x{2,0}, y{0,1}, negative{-2,0};
    assert(std::abs(cosine(x,x)-1) < 1e-12);
    assert(std::abs(cosine(x,y)) < 1e-12);
    assert(std::abs(cosine(x,negative)+1) < 1e-12);
    assert(std::abs(cosine(x,y)-cosine(y,x)) < 1e-12);
    const auto avg = mean({x,y});
    assert(avg[0] == 1 && avg[1] == .5f);
    assert(std::abs(cosine(x,avg) - 2/std::sqrt(5.0)) < 1e-12);
    assert(std::abs(cosine(y,avg) - 1/std::sqrt(5.0)) < 1e-12);
    assert(mean({x}) == x);
    bool rejected = false;
    try { mean({}); } catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);
    rejected = false;
    try { mean({x,negative}); } catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);
    rejected = false;
    try { cosine(x,{0,0}); } catch (const std::invalid_argument &) { rejected = true; }
    assert(rejected);
    std::cout << "Native reference cosine/mean checks passed\n";
}

#include "util.h"

int clamp(int value, int lo, int hi) {
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
}

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);  /* recursive call: self-edge expected */
}

int compute(int raw) {
    int bounded = clamp(raw, 0, 100);
    return factorial(bounded);
}

int cGlobalCounter = 0;

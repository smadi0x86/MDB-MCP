#include <stdio.h>
#include <stdlib.h>

int factorial(int n) {
    if (n <= 1) {
        return 1;
    }

    return n * factorial(n - 1);
}

int main() {
    int number = 5;
    int result;

    printf("Calculating factorial of %d\n", number);

    result = factorial(number);

    printf("Factorial of %d is %d\n", number, result);

    return 0;
}
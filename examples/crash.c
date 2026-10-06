#include <stdio.h>
#include <string.h>

struct user {
    char name[16];
    int age;
};

static struct user *find_user(struct user *users, int count, const char *name) {
    for (int i = 0; i < count; i++) {
        if (strcmp(users[i].name, name) == 0) {
            return &users[i];
        }
    }
    return NULL;
}

int main(void) {
    struct user users[] = {{"alice", 31}, {"bob", 27}};
    const char *names[] = {"alice", "bob", "carol"};

    for (int i = 0; i < 3; i++) {
        struct user *u = find_user(users, 2, names[i]);
        printf("%s is %d years old\n", u->name, u->age);
    }
    return 0;
}

CC ?= cc
CFLAGS ?= -g -O0

PROGRAMS = example crash

all: $(PROGRAMS)

%: %.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(PROGRAMS)

.PHONY: all clean

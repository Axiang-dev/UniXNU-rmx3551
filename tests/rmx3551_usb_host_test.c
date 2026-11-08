/* Host test for the liuqin USB debug port logic (no kernel needed).
 * Build: gcc -DLIUQIN_HOST_TEST -I. liuqin_usb_host_test.c -o /tmp/lqtest
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "liuqin_log_ring.h"
#include "liuqin_usb_protocol.h"

static int fails;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #cond); fails++; } } while (0)

int main(void)
{
	/* --- ring: keeps the newest 1 MiB, never invents bytes --- */
	static struct lq_ring r;
	static char out[4096];
	for (unsigned i = 0; i < 3u << 20; i++) {
		char c = (char)('a' + (i % 26));
		lq_append(&r, &c, 1);
	}
	CHECK(r.total == (3u << 20));
	CHECK(LQ_RING_SIZE == (1u << 20));
	uint64_t pos = 0;
	unsigned n = lq_copy(&r, &pos, out, 16);
	CHECK(n == 16);
	unsigned base = (3u << 20) - LQ_RING_SIZE;
	for (unsigned i = 0; i < 16; i++) {
		CHECK(out[i] == (char)('a' + ((base + i) % 26)));
	}
	/* a stale cursor is clamped forward, not wrapped backwards */
	pos = 5;                       /* stale cursor: clamped to the oldest retained byte */
	n = lq_copy(&r, &pos, out, 8);
	CHECK(n == 8 && pos == (uint64_t)base + 8);
	CHECK(out[0] == (char)('a' + (base % 26)));
	/* oversized append keeps only the tail */
	struct lq_ring *big = calloc(1, sizeof(*big));
	static char block[8192];
	memset(block, 'z', sizeof(block));
	block[sizeof(block) - 1] = 'Q';
	lq_append(big, block, sizeof(block));
	uint64_t bp = sizeof(block) - 4;
	n = lq_copy(big, &bp, out, 4);
	CHECK(n == 4 && out[3] == 'Q' && out[0] == 'z');
	free(big);

	/* --- request whitelist: only the published control transfers --- */
	CHECK(lqusb_request(0x80, 6, 0x0100, 0, 18) == LQUSB_DESC);
	CHECK(lqusb_request(0x80, 6, 0x0200, 0, 67) == LQUSB_DESC);
	CHECK(lqusb_request(0x00, 5, 7, 0, 0) == LQUSB_ADDRESS);
	CHECK(lqusb_request(0x00, 9, 1, 0, 0) == LQUSB_CONFIG);
	CHECK(lqusb_request(0x80, 8, 0, 0, 1) == LQUSB_GET_CONFIG);
	CHECK(lqusb_request(0x21, 0x20, 0, 0, 7) == LQUSB_SET_LINE);
	CHECK(lqusb_request(0x21, 0x22, 3, 0, 0) == LQUSB_CONTROL);
	CHECK(lqusb_request(0xa1, 0x21, 0, 0, 7) == LQUSB_GET_LINE);
	CHECK(lqusb_request(0x02, 1, 0, 0x81, 0) == LQUSB_CLEAR_HALT);
	/* rejected shapes */
	CHECK(lqusb_request(0x21, 0x20, 0, 0, 8) == LQUSB_BAD);      /* wrong CDC length */
	CHECK(lqusb_request(0x00, 9, 2, 0, 0) == LQUSB_BAD);         /* config value 2 */
	CHECK(lqusb_request(0x00, 5, 128, 0, 0) == LQUSB_BAD);       /* address 128 */
	CHECK(lqusb_request(0x40, 1, 0, 0, 0) == LQUSB_BAD);         /* class OUT, unknown */
	CHECK(lqusb_request(0x02, 1, 0, 0x02, 0) == LQUSB_BAD);      /* clear-halt ep 2 */
	CHECK(lqusb_request(0x21, 0x22, 4, 0, 0) == LQUSB_BAD);      /* bad control value */
	CHECK(lqusb_request(0x80, 6, 0x0800, 0, 9) == LQUSB_BAD);    /* descriptor 8 */

	/* --- descriptors are self consistent --- */
	CHECK(lqusb_device[0] == 18 && lqusb_device[1] == 1);
	CHECK(lqusb_device[8] == 0x09 && lqusb_device[9] == 0x12);   /* 1209 */
	CHECK(lqusb_device[10] == 0x02 && lqusb_device[11] == 0x00); /* 0002 */
	CHECK(lqusb_config[0] == 9 && lqusb_config[2] == 67 && lqusb_config[1] == 2);
	CHECK(sizeof(lqusb_config) == 67);
	CHECK(lqusb_qualifier[0] == 10 && lqusb_qualifier[7] == 64);

	/* --- DMA window predicate --- */
	CHECK(lqusb_dma_allowed(0x80000000ULL, 0x4000, 40, 0x80000000ULL, 0x100000000ULL));
	CHECK(lqusb_dma_allowed(0x8fffc000ULL, 0x4000, 40, 0x80000000ULL, 0x90000000ULL));  /* ends at window edge */
	CHECK(!lqusb_dma_allowed(0x8ffff000ULL, 0x4000, 40, 0x80000000ULL, 0x90000000ULL)); /* crosses the edge */
	CHECK(!lqusb_dma_allowed(0x80002000ULL, 0x4000, 40, 0x80000000ULL, 0x100000000ULL)); /* misaligned */
	CHECK(lqusb_dma_allowed(0x100000000ULL, 0x4000, 40, 0x80000000ULL, 0x200000000ULL)); /* 4 GiB, width 40 */
	CHECK(!lqusb_dma_allowed(0x100000000ULL, 0x4000, 32, 0x80000000ULL, 0x200000000ULL)); /* exceeds 32-bit */
	CHECK(lqusb_dma_allowed(0x100000000ULL, 0x4000, 64, 0x80000000ULL, 0x200000000ULL));
	CHECK(!lqusb_dma_allowed(0x0, 0x4000, 40, 0x80000000ULL, 0x100000000ULL));

	/* --- SMMU stream/route predicates --- */
	CHECK(lqusb_stream_match(0x80000000U, 0));                  /* SID 0, no mask */
	CHECK(!lqusb_stream_match(0x00000000U, 0));                 /* valid bit clear */
	CHECK(lqusb_stream_match(0x80000000U | (0 << 16), 0));
	CHECK(lqusb_stream_match(0x80000005U | (0x3 << 16), 5));    /* SID 5 with mask 3 */
	CHECK(lqusb_route_identity(1u << 16, 0, 1));                /* bypass/identity */
	CHECK(lqusb_route_identity(0u, (1u << 16), 0));             /* translation, CBAR type 1, SCTLR off */
	CHECK(!lqusb_route_identity(0u, (1u << 16), 1));            /* translation enabled */
	CHECK(!lqusb_route_identity(2u << 16, 0, 0));               /* fault */

	if (fails) {
		printf("%d check(s) failed\n", fails);
		return 1;
	}
	printf("all liuqin usb debug host checks passed\n");
	return 0;
}

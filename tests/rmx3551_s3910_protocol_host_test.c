#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "pong_s3910_protocol.h"

static unsigned failures;

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
		failures++; \
	} \
} while (0)

int
main(void)
{
	static const uint8_t ascii[] = "123456789";
	uint8_t read_buffer[19];
	uint8_t head[4] = { 0x23, 0x08, 0x00, 0x00 };
	uint8_t report[] = {
		3,
		4, 1, 0xc0, 0x21, 0x60, 0x4b,
		7, 2, 0xe0, 0x10, 0xb0, 0x25,
		2, 9, 0x64, 0x00, 0xc8, 0x00
	};
	struct s3910_frame frame;

	CHECK(s3910_le16((const uint8_t *)"\x34\x12") == 0x1234);
	CHECK(s3910_le32((const uint8_t *)"\x78\x56\x34\x12") == 0x12345678u);
	CHECK(s3910_crc6(ascii, 0) == 0x3f);
	CHECK(s3910_crc6(ascii, 9 * 8) == 0x01);
	CHECK(s3910_crc16(ascii, 9) == 0x29b1);
	head[3] |= s3910_crc6(head, 26);
	CHECK(head[3] == 0x2e);

	memset(read_buffer, 0, sizeof(read_buffer));
	s3910_prepare_read(read_buffer, sizeof(read_buffer));
	for (unsigned i = 0; i < sizeof(read_buffer); i++) {
		CHECK(read_buffer[i] == 0xff);
	}

	CHECK(s3910_decode(report, sizeof(report), 8640, 19296, &frame) == 0);
	CHECK(frame.contact[4].active == 1);
	CHECK(frame.contact[4].x == 65535);
	CHECK(frame.contact[4].y == 65535);
	CHECK(frame.contact[7].active == 1);
	CHECK(frame.contact[7].x == (uint16_t)(4320u * 65535u / 8640u));
	CHECK(frame.contact[7].y == (uint16_t)(9648u * 65535u / 19296u));
	CHECK(frame.contact[2].active == 0);

	report[7] = 4; /* duplicate object id */
	CHECK(s3910_decode(report, sizeof(report), 8640, 19296, &frame) == -71);
	report[7] = 7;
	report[3] = 0xd0; /* x = 8656, beyond the panel coordinate */
	CHECK(s3910_decode(report, sizeof(report), 8640, 19296, &frame) == -71);
	report[3] = 0xc0;
	CHECK(s3910_decode(report, sizeof(report) - 1, 8640, 19296, &frame) == -71);

	if (failures) {
		fprintf(stderr, "%u S3910 protocol checks failed\n", failures);
		return 1;
	}
	puts("S3910 protocol host tests passed");
	return 0;
}

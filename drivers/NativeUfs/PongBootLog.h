/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Pong boot log in storage.
 *
 * The kernel already mirrors its console into the ramoops reserve the device
 * tree hands it (osfmk/arm64/pong_ramoops_console.h: a 12-byte persistent_ram
 * header, 2 MiB console ring, then 2 MiB diagnostic zone). That mirror lives in
 * RAM, so a panic takes it with it and the screen is the only copy.
 *
 * This copies the mirror into a reserved region just past the flashed image,
 * inside the userdata partition, within two seconds of the console changing.
 * A reader running later (recovery with root adb) pulls that region with dd,
 * so the log survives a panic, a hang and a power cycle.
 *
 * Region layout, little endian:
 *   +0x0000  4096  header: "PBLOG001", mirror bytes, sequence, status, digest
 *   +0x1000  4 MiB the ramoops mirror exactly as the kernel wrote it
 * The header is written last, so a torn snapshot keeps the previous one valid.
 *
 * Included from PongUfsTransport.cpp: it needs gHost, the 4 KiB write path and
 * mapPhys() from that translation unit, and the caller passes the region from
 * the SHNGROOT layout it already parsed.
 */
namespace PongBootLog {
enum : uint64_t {
  kMirrorPhys  = 0x85200000ULL,
  kMirrorBytes = 4ULL << 20,
  kHeaderBytes = 4096ULL,
  kRegionBytes = kHeaderBytes + kMirrorBytes,
};

static uint64_t gRegionLba;
static uint64_t gRegionBlocks;
static uintptr_t gMirror;
static OSSharedPtr<IOMemoryMap> gMirrorMap;
static volatile uint32_t gStarted;
static uint32_t gSequence;
static uint32_t gWrites, gFailures;

static bool writeBlocks(uint64_t lba, const void *source, uint64_t bytes) {
  if (!source || !bytes || (bytes & 4095) || !gHost.ready || gHost.poisoned || !gHost.writable)
    return false;
  uint64_t done = 0;
  while (done < bytes) {
    uint64_t take = bytes - done;
    if (take > kDataMax) take = kDataMax;
    IOLockLock(gHost.lock);
    bool ok = gHost.ready && !gHost.poisoned && hostIdle();
    if (ok) {
      memcpy(gHost.virt + kDataOffset, static_cast<const uint8_t *>(source) + done, take);
      cacheCivac(gHost.virt + kDataOffset, take);
      ok = hostWrite4kLocked(0, lba + done / 4096, static_cast<uint32_t>(take / 4096)) ==
           kIOReturnSuccess;
    }
    IOLockUnlock(gHost.lock);
    if (!ok) return false;
    done += take;
  }
  return true;
}

struct Header {
  char magic[8];
  uint32_t mirrorBytes;
  uint32_t sequence;
  uint32_t status;          /* 1 = this snapshot is complete */
  uint32_t crc32;           /* reflected IEEE CRC32 of the mirror, same as zlib.crc32 */
  uint64_t mirrorPhysical;
  uint32_t reserved[8];
};

static void snapshot() {
  if (!gMirror || !gHost.ready || gHost.poisoned) return;
  /* The kernel cleans the lines it writes; drop ours so the copy is current. */
  cacheInvalidate(reinterpret_cast<const void *>(gMirror), kMirrorBytes);
  const auto *mirror = reinterpret_cast<const uint8_t *>(gMirror);
  const uint64_t first = gRegionLba + kHeaderBytes / 4096;
  if (!writeBlocks(first, mirror, kMirrorBytes)) {
    gFailures++;
    return;
  }
  /* Header last: a torn data write leaves the previous complete snapshot. */
  static Header header;
  memset(&header, 0, sizeof(header));
  memcpy(header.magic, "PBLOG001", 8);
  header.mirrorBytes = static_cast<uint32_t>(kMirrorBytes);
  header.sequence = ++gSequence;
  header.status = 1;
  header.crc32 = rootCrc32(mirror, kMirrorBytes);
  header.mirrorPhysical = kMirrorPhys;
  if (!writeBlocks(gRegionLba, &header, kHeaderBytes)) {
    gFailures++;
    return;
  }
  gWrites++;
}

/* The persistent_ram header opens the mirror: magic, then the ring's start and
 * size. Those two move only when the kernel writes to the console, so they make
 * a cheap dirty flag and let the writer poll often without paying for a 4 MiB
 * snapshot on every tick. */
static uint32_t gLastStart = 0xffffffffU, gLastSize = 0xffffffffU;

static bool consoleChanged() {
  cacheInvalidate(reinterpret_cast<const void *>(gMirror), 16);
  const auto *head = reinterpret_cast<const volatile uint32_t *>(gMirror);
  const uint32_t sig = head[0], start = head[1], size = head[2];
  if (sig != 0x43474244U) return true;  /* not the ring we expect: never skip */
  if (start == gLastStart && size == gLastSize) return false;
  gLastStart = start;
  gLastSize = size;
  return true;
}

static void worker(void *, wait_result_t) {
  /* Give storage and the console a moment to be up before the first copy. */
  IOSleep(2000);
  for (;;) {
    if (consoleChanged()) snapshot();
    IOSleep(2000);
  }
}

/* Called once, after the SHNGROOT layout parsed and the host is ready. */
static void start(uint64_t firstLba, uint64_t bytes) {
  if (!firstLba || !bytes || (bytes & 4095) || bytes < kRegionBytes) return;
  if (__atomic_exchange_n(&gStarted, 1, __ATOMIC_ACQ_REL)) return;
  gRegionLba = firstLba;
  gRegionBlocks = bytes / 4096;
  gMirror = mapPhys(kMirrorPhys, kMirrorBytes, gMirrorMap);
  if (!gMirror) {
    IOLog("PongBootLog: ramoops mirror not mappable; storage log disabled\n");
    return;
  }
  thread_t thread = nullptr;
  if (kernel_thread_start(worker, nullptr, &thread) != KERN_SUCCESS) {
    IOLog("PongBootLog: worker thread refused\n");
    return;
  }
  thread_deallocate(thread);
  IOLog("PongBootLog: %llu KiB mirror to userdata LBA %llu, every 2s when it changes\n",
        kMirrorBytes >> 10, gRegionLba);
}
}  /* namespace PongBootLog */

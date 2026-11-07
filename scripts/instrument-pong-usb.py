#!/usr/bin/env python3
"""Make the USB transport's state survive log scrolling.

PongUsb prints its handoff/PMIC diagnostics once, seconds before launchd floods
the console; by the time the machine panics those lines are thousands of lines
up and a photo of the screen cannot recover them.  This adds:

* a line when start() is entered, with the boot-arg value, so "the driver never
  ran" and "the driver ran and refused" stop looking the same;
* a line with the handoff / DMA / PHY results before the first controller read;
* a status thread that reprints handoff, DMA, root-transport, controller and
  PMIC state every 8 seconds for 96 seconds, so whatever the boot is doing when
  it stops, the last screen holds the USB state.

Applied to the pinned PongUsb submodule checkout; exact string replacement, and
the build stops if the source no longer matches.
"""
import argparse
import sys
from pathlib import Path

STATUS_THREAD = '''static void statusThread(void *,wait_result_t) {
 for(unsigned i=0;i<12;i++){
  IOSleep(8000);
  IOLog("PongUSB status %us: handoff=%u dma=%u addr=%llx ufs=%u configured=%u cable=%u failed=%u stage=%u status=%d\\n",
   (i+1)*8,handoffSeen?1u:0u,dmaSeen?1u:0u,(unsigned long long)physical,pong_ufs_ready()?1u:0u,
   configured?1u:0u,cableConnected?1u:0u,failed?1u:0u,stage,statusDep);
 }
 thread_terminate(current_thread());thread_block(THREAD_CONTINUE_NULL);
}
'''

HANDOFF_BEFORE = ''' bool firmwarePhy=false;
 if(!PongLowDma::usbHandoff(&firmwarePhy) || !PongLowDma::usbAddress(physical)) {'''
HANDOFF_AFTER = ''' bool firmwarePhy=false;
 handoffSeen=PongLowDma::usbHandoff(&firmwarePhy);
 dmaSeen=handoffSeen&&PongLowDma::usbAddress(physical);
 IOLog("PongUSB: handoff=%u dma=%u phy=%u\\n",handoffSeen?1u:0u,dmaSeen?1u:0u,firmwarePhy?1u:0u);
 if(!handoffSeen || !dmaSeen) {'''

START_BEFORE = ''' unsigned enabled=0;if(!PE_parse_boot_argn("pong_usb",&enabled,sizeof(enabled)) || enabled!=1)return;'''
START_AFTER = ''' unsigned enabled=0;PE_parse_boot_argn("pong_usb",&enabled,sizeof(enabled));
 IOLog("PongUSB: start called with pong_usb=%u\\n",enabled);
 if(enabled!=1)return;'''

WORKER_CALL = ''' thread_t t=nullptr;if(kernel_thread_start(worker,nullptr,&t)==KERN_SUCCESS)thread_deallocate(t);'''
WORKER_CALL_AFTER = WORKER_CALL + '''
 thread_t late=nullptr;if(kernel_thread_start(statusThread,nullptr,&late)==KERN_SUCCESS)thread_deallocate(late);'''

WORKER_DEF = 'static void worker(void *,wait_result_t) {'

# The state flags have to exist before initialize() reads them, so they join the
# other file-scope statics rather than the status thread block.
DECL_BEFORE = 'static bool cableConnected;'
DECL_AFTER = 'static bool cableConnected;\nstatic bool handoffSeen,dmaSeen;'


def replace_once(text, old, new, marker, label):
    if marker in text:
        print(f'{label}: already applied')
        return text
    if old not in text:
        raise SystemExit(f'{label}: expected source text not found; refusing to guess')
    print(f'{label}: patched')
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='drivers/PongUsb/PongUsbDevice.h of the pinned submodule')
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8')
    if 'static void worker(void *,wait_result_t) {' not in text:
        raise SystemExit(f'{args.source}: no worker(); the pinned driver changed')
    if 'static void statusThread' not in text:
        text = text.replace(WORKER_DEF, STATUS_THREAD + WORKER_DEF, 1)
        print('status thread: added')
    text = replace_once(text, DECL_BEFORE, DECL_AFTER, 'handoffSeen,dmaSeen', 'state declaration')
    text = replace_once(text, HANDOFF_BEFORE, HANDOFF_AFTER, 'handoffSeen=', 'handoff log')
    text = replace_once(text, START_BEFORE, START_AFTER, 'PongUSB: start called with', 'start log')
    text = replace_once(text, WORKER_CALL, WORKER_CALL_AFTER, 'statusThread,nullptr', 'status thread start')
    args.source.write_text(text, encoding='utf-8')
    print(f'{args.source}: {len(text)} bytes')


if __name__ == '__main__':
    sys.exit(main())

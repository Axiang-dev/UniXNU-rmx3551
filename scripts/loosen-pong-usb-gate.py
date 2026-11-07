#!/usr/bin/env python3
"""Let the USB console start without the audio meta-classes.

PongPower.cpp starts the USB transport like this:

    if (pong_audio_service_classes_ready()) PongUsb::start();

which couples the only log channel this board has to whether the audio classes
registered.  When audio fails -- exactly the case where the console is worth
most -- PongUsb::start() is never called and the driver prints nothing at all,
so the screen cannot say why USB is silent either.  The transport itself needs
nothing from audio: it publishes after its own SMMU/DMA/PMIC work succeeds.

The driver lives in a pinned submodule, so the edit is applied to the checkout
instead of a fork: exact string replacement, idempotent, and loud when the
pinned source no longer contains the line.
"""
import argparse
import sys
from pathlib import Path

GATE = ' if(pong_audio_service_classes_ready())PongUsb::start();'
REPLACEMENT = ''' // The USB CDC console is the only log channel this board has before the
 // display can show anything, so it must not wait on the audio classes.
 const bool audioClassesReady=pong_audio_service_classes_ready();
 IOLog("PongPower: audio classes ready=%u; starting the USB transport anyway\\n",
       audioClassesReady?1u:0u);
 PongUsb::start();'''
INCLUDE_AFTER = '#include <IOKit/IOService.h>'
INCLUDE = '#include <IOKit/IOLib.h>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='drivers/PongPower/PongPower.cpp of the pinned submodule')
    args = parser.parse_args()

    text = args.source.read_text(encoding='utf-8')
    if 'PongUsb::start();' not in text:
        raise SystemExit(f'{args.source}: no PongUsb::start() call; the pinned driver changed')
    if GATE in text:
        text = text.replace(GATE, REPLACEMENT, 1)
        print('gate removed')
    elif 'audioClassesReady' in text:
        print('gate already removed')
    else:
        raise SystemExit(f'{args.source}: the audio gate is not the expected line; '
                         'refusing to guess')
    if INCLUDE not in text:
        if INCLUDE_AFTER not in text:
            raise SystemExit(f'{args.source}: {INCLUDE_AFTER} not found')
        text = text.replace(INCLUDE_AFTER, INCLUDE_AFTER + '\n' + INCLUDE, 1)
        print('IOLog included')
    args.source.write_text(text, encoding='utf-8')
    for line in text.splitlines():
        if 'PongUsb::start()' in line or 'audioClassesReady=' in line:
            print('  ' + line.strip())


if __name__ == '__main__':
    sys.exit(main())

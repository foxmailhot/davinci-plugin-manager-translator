"""Build the OFX adapter with Zig 0.13 or a compatible Windows C compiler."""
from pathlib import Path
import argparse
import subprocess

def build(compiler, output):
    folder = Path(__file__).resolve().parent / 'native'
    count = 2048
    text = '\n'.join(f'static void set_host_{i}(OfxHost *h) {{ set_host_index({i},h); }}' for i in range(count))
    text += '\nstatic void (*setters[])(OfxHost *) = {' + ','.join(f'set_host_{i}' for i in range(count)) + '};\n'
    (folder/'setters.inc').write_text(text,encoding='utf-8')
    output = Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(compiler),'cc','-shared','-std=c11','-O2','-target','x86_64-windows-gnu',
                    '-I',str(folder/'include'),str(folder/'proxy.c'),'-o',str(output)],check=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--zig',required=True); parser.add_argument('--output',default=str(Path(__file__).parent/'assets'/'translation_proxy.ofx'))
    args=parser.parse_args(); build(args.zig,args.output)

"""Build the OFX adapter with Zig 0.13 or a compatible Windows C compiler."""
from pathlib import Path
import argparse
import subprocess
import re

def build(compiler, output):
    folder = Path(__file__).resolve().parent / 'native'
    count = 512
    declarations=re.findall(r'OfxStatus\s*\(\*(\w+)\)\s*\(([^;]+)\);',(folder/'include'/'ofxProperty.h').read_text())
    if len(declarations)!=18: raise RuntimeError('Unexpected OFX PropertySuite layout')
    functions=[]
    signatures=[]
    for name,args in declarations:
        arguments=','.join(re.search(r'(\w+)\s*$',value.strip()).group(1) for value in args.split(','))
        signatures.append((name,args,arguments))
        if name=='propSetString':call='set_string_index(slot,'+arguments+')'
        elif name=='propSetStringN':call='set_strings_index(slot,'+arguments+')'
        else:call=f'props->{name}({arguments})'
        prefix='' if name in ('propSetString','propSetStringN') else f'const OfxPropertySuiteV1 *props=current_props(slot); if(!props || !props->{name}) return kOfxStatErrMissingHostFeature; '
        functions.append(f'static OfxStatus forward_{name}(int slot,{args}) {{ {prefix}return {call}; }}')
    (folder/'forwarders.inc').write_text('\n'.join(functions)+'\n',encoding='utf-8')
    text = '\n'.join(f'''static void set_host_{i}(OfxHost *h) {{ set_host_index({i},h); }}
static const void *fetch_{i}(OfxPropertySetHandle h,const char *n,int v) {{ return fetch_suite_index({i},h,n,v); }}
static OfxStatus entry_{i}(const char *a,const void *h,OfxPropertySetHandle in,OfxPropertySetHandle out) {{ return main_index({i},a,h,in,out); }}''' for i in range(count))
    for i in range(count):
        for name,args,arguments in signatures:
            text+=f'\nstatic OfxStatus property_{i}_{name}({args}) {{ return forward_{name}({i},{arguments}); }}'
    text += '\nstatic const Callbacks callbacks[] = {' + ','.join(f'{{set_host_{i},fetch_{i},entry_{i},{{'+','.join(f'property_{i}_{name}' for name,_,_ in signatures)+'}}' for i in range(count)) + '};\n'
    (folder/'setters.inc').write_text(text,encoding='utf-8')
    output = Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(compiler),'cc','-shared','-std=c11','-O2','-target','x86_64-windows-gnu',
                    '-I',str(folder/'include'),str(folder/'proxy.c'),'-o',str(output)],check=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--zig',required=True); parser.add_argument('--output',default=str(Path(__file__).parent/'assets'/'translation_proxy.ofx'))
    args=parser.parse_args(); build(args.zig,args.output)

from pathlib import Path
import argparse
import hashlib
import zipfile

def package(folder,output):
    folder=Path(folder); output=Path(output); output.mkdir(parents=True,exist_ok=True)
    archive=output/'ResolvePluginManager-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for file in sorted(folder.iterdir()):
            if file.is_file() and file.suffix.lower() in ('.exe','.md','.txt'): z.write(file,file.name)
    checksum=archive.with_name(archive.name+'.sha256')
    checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n',encoding='utf-8')
    print(archive);print(checksum)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('output');args=p.parse_args();package(args.folder,args.output)

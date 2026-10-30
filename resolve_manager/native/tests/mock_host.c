#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "ofxCore.h"
#include "ofxProperty.h"
static int labels,names,defaults,choices,numbers,failures;
static const char *zh="\xe4\xba\xae\xe5\xba\xa6";
static OfxStatus set_string(OfxPropertySetHandle h,const char *p,int index,const char *value){
    if(!strcmp(p,"OfxPropLabel")){labels++; if(strcmp(value,zh)) failures++;}
    if(!strcmp(p,"OfxPropName")){names++; if(strcmp(value,"Brightness")) failures++;}
    if(!strcmp(p,"OfxParamPropDefault")){defaults++; if(strcmp(value,"Brightness")) failures++;}
    return 0;
}
static OfxStatus set_many(OfxPropertySetHandle h,const char *p,int n,const char *const *v){
    choices++; if(strcmp(p,"OfxParamPropChoiceOption")||n!=2||strcmp(v[0],zh)||strcmp(v[1],"Untranslated")) failures++; return 0;
}
static OfxStatus set_int(OfxPropertySetHandle h,const char *p,int index,int value){numbers++; if(value!=7&&value!=8) failures++; return 0;}
static OfxPropertySuiteV1 suite;
static const void *fetch(OfxPropertySetHandle h,const char *name,int version){return !strcmp(name,kOfxPropertySuite)&&version==1?&suite:NULL;}
int main(int argc,char **argv){
    if(argc!=2)return 1;
    HMODULE module=LoadLibraryA(argv[1]); if(!module){printf("Load failed %lu",GetLastError());return 2;}
    int (*count)(void)=(void *)GetProcAddress(module,"OfxGetNumberOfPlugins");
    OfxPlugin *(*plugin)(int)=(void *)GetProcAddress(module,"OfxGetPlugin");
    if(!count||!plugin||count()!=2||plugin(-1)||plugin(2))return 3;
    suite.propSetString=set_string;suite.propSetStringN=set_many;suite.propSetInt=set_int;
    OfxHost host={NULL,fetch};
    for(int i=0;i<2;i++){
        OfxPlugin *p=plugin(i);
        if(p->pluginVersionMajor!=2||p->pluginVersionMinor!=3||strncmp(p->pluginIdentifier,"test.original.",14))return 4;
        p->setHost(&host);
        if(p->mainEntry("test.action",NULL,NULL,NULL)!=42+i)return 5;
    }
    if(labels!=2||names!=2||defaults!=2||choices!=2||numbers!=2||failures){printf("failed checks %d",failures);return 6;}
    puts("PASS: labels, choice arrays, identifiers, defaults, numbers, callbacks and entry points");
    return 0;
}

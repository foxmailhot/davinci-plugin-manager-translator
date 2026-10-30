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
static OfxPropertySuiteV1 suite_b;
static int active_index;
static OfxStatus set_a(OfxPropertySetHandle h,const char *p,int i,const char *v){if(active_index!=0)failures++;return set_string(h,p,i,v);}
static OfxStatus set_b(OfxPropertySetHandle h,const char *p,int i,const char *v){if(active_index!=1)failures++;return set_string(h,p,i,v);}
static const void *fetch_a(OfxPropertySetHandle h,const char *name,int version){if(h!=(void *)1)failures++;return !strcmp(name,kOfxPropertySuite)&&version==1?&suite:NULL;}
static const void *fetch_b(OfxPropertySetHandle h,const char *name,int version){if(h!=(void *)2)failures++;return !strcmp(name,kOfxPropertySuite)&&version==1?&suite_b:NULL;}
static const void *fetch(OfxPropertySetHandle h,const char *name,int version){return !strcmp(name,kOfxPropertySuite)&&version==1?&suite:NULL;}
int main(int argc,char **argv){
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    if(argc<2)return 1;
    HMODULE module=LoadLibraryA(argv[1]); if(!module){printf("Load failed %lu",GetLastError());return 2;}
    int (*count)(void)=(void *)GetProcAddress(module,"OfxGetNumberOfPlugins");
    OfxPlugin *(*plugin)(int)=(void *)GetProcAddress(module,"OfxGetPlugin");
    if(!count||!plugin||count()!=2||plugin(-1)||plugin(2))return 3;
    suite.propSetString=set_string;suite.propSetStringN=set_many;suite.propSetInt=set_int;
    OfxHost host={NULL,fetch};
    if(argc>2 && !strcmp(argv[2],"missing-reader")){
        OfxPlugin *p=plugin(0);p->setHost(&host);
        if(p->mainEntry("read_host",NULL,NULL,NULL)!=kOfxStatErrMissingHostFeature)return 25;
        puts("PASS: missing read callbacks return an error instead of calling NULL");return 0;
    }
    if(argc>2 && !strcmp(argv[2],"cached-reload")){
        OfxPlugin *first=plugin(0);first->setHost(&host);
        if(first->mainEntry("cache_test",NULL,NULL,NULL)!=42)return 30;
        FreeLibrary(module);
        module=LoadLibraryA(argv[1]);if(!module)return 31;
        plugin=(void *)GetProcAddress(module,"OfxGetPlugin");
        OfxPlugin *second=plugin(1);second->setHost(&host);
        if(second->mainEntry("cache_test",NULL,NULL,NULL)!=43)return 32;
        puts("PASS: cached vendor callbacks survive adapter unload/reload");return 0;
    }
    if(argc>2 && !strcmp(argv[2],"isolation")){
        suite.propSetString=set_a;suite_b=suite;suite_b.propSetString=set_b;
        host.host=(void *)1;host.fetchSuite=fetch_a;plugin(0)->setHost(&host);
        host.host=(void *)2;host.fetchSuite=fetch_b;plugin(1)->setHost(&host);
        for(int i=0;i<2;i++){active_index=i;if(plugin(i)->mainEntry("test",NULL,NULL,NULL)!=42+i)return 20;}
        if(failures)return 21;puts("PASS: independent host snapshots");return 0;
    }
    if(argc>2 && !strcmp(argv[2],"borrowed-suite")){
        OfxPlugin *p=plugin(0);p->setHost(&host);
        if(p->mainEntry("test",NULL,NULL,NULL)!=42)return 22;
        suite.propSetString=NULL;suite.propSetStringN=NULL;
        if(p->mainEntry("test",NULL,NULL,NULL)!=kOfxStatErrMissingHostFeature)return 23;
        puts("PASS: changed host tables return an error instead of calling NULL");return 0;
    }
    if(argc>2 && (!strcmp(argv[2],"missing-string") || !strcmp(argv[2],"missing-array"))){
        if(!strcmp(argv[2],"missing-string"))suite.propSetString=NULL;else suite.propSetStringN=NULL;
        OfxPlugin *p=plugin(0);p->setHost(&host);
        if(p->mainEntry("test",NULL,NULL,NULL)!=kOfxStatErrMissingHostFeature)return 24;
        puts("PASS: missing callbacks return an error instead of calling NULL");return 0;
    }
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

#include "ofxCore.h"
#include "ofxProperty.h"
#include <stddef.h>
static OfxHost *hosts[2];
static void host0(OfxHost *host){hosts[0]=host;}
static void host1(OfxHost *host){hosts[1]=host;}
static OfxStatus run(int index,const char *action,const void *handle,OfxPropertySetHandle in,OfxPropertySetHandle out){
    if(!hosts[index]) return -10;
    const OfxPropertySuiteV1 *p=hosts[index]->fetchSuite(hosts[index]->host,kOfxPropertySuite,1);
    if(!p) return -11;
    p->propSetString(out,"OfxPropLabel",0,"Brightness");
    p->propSetString(out,"OfxPropName",0,"Brightness");
    p->propSetString(out,"OfxParamPropDefault",0,"Brightness");
    const char *choices[]={"Brightness","Untranslated"};
    p->propSetStringN(out,"OfxParamPropChoiceOption",2,choices);
    p->propSetInt(out,"OfxParamPropDefault",0,7+index);
    return 42+index;
}
static OfxStatus run0(const char *a,const void *h,OfxPropertySetHandle i,OfxPropertySetHandle o){return run(0,a,h,i,o);}
static OfxStatus run1(const char *a,const void *h,OfxPropertySetHandle i,OfxPropertySetHandle o){return run(1,a,h,i,o);}
static OfxPlugin plugins[]={
    {"OfxImageEffectPluginAPI",1,"test.original.0",2,3,host0,run0},
    {"OfxImageEffectPluginAPI",1,"test.original.1",2,3,host1,run1}
};
__declspec(dllexport) int OfxGetNumberOfPlugins(void){return 2;}
__declspec(dllexport) OfxPlugin *OfxGetPlugin(int index){return index>=0&&index<2?&plugins[index]:NULL;}

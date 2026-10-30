/* OFX display-text adapter. Rendering, identifiers and values remain in the original module. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ofxCore.h"
#include "ofxProperty.h"

#define MAX_PLUGINS 2048
static HMODULE original_module;
static OfxPlugin *originals[MAX_PLUGINS], copies[MAX_PLUGINS];
static OfxHost *real_host;
static OfxHost bridge_host;
static const OfxPropertySuiteV1 *real_props;
static OfxPropertySuiteV1 bridge_props;
static INIT_ONCE init_once = INIT_ONCE_STATIC_INIT;
static SRWLOCK suite_lock = SRWLOCK_INIT;
static int (*get_count)(void);
static OfxPlugin *(*get_plugin)(int);
static char **keys, **values;
static size_t word_count;

static char *unescape(char *s) {
    char *out = s, *p = s;
    while (*p) {
        if (*p == '\\' && p[1]) {
            ++p;
            *out++ = *p == 'n' ? '\n' : *p == 'r' ? '\r' : *p == 't' ? '\t' : *p;
            ++p;
        } else *out++ = *p++;
    }
    *out = 0; return s;
}

static int display_property(const char *p) {
    return p && (!strcmp(p,"OfxPropLabel") || !strcmp(p,"OfxPropShortLabel") ||
        !strcmp(p,"OfxPropLongLabel") || !strcmp(p,"OfxPropPluginDescription") ||
        !strcmp(p,"OfxParamPropHint") || !strcmp(p,"OfxParamPropChoiceOption") ||
        !strcmp(p,"OfxImageEffectPluginPropGrouping"));
}

static const char *translated(const char *text) {
    if (!text) return text;
    size_t lo=0,hi=word_count;
    while(lo<hi) { size_t mid=lo+(hi-lo)/2; int cmp=strcmp(keys[mid],text);
        if(!cmp) return values[mid]; if(cmp<0) lo=mid+1; else hi=mid; }
    return text;
}

static OfxStatus set_string(OfxPropertySetHandle h,const char *p,int i,const char *v) {
    return real_props->propSetString(h,p,i,display_property(p)?translated(v):v);
}

static OfxStatus set_strings(OfxPropertySetHandle h,const char *p,int n,const char *const *v) {
    if (!display_property(p) || n<=0 || !v) return real_props->propSetStringN(h,p,n,v);
    const char **result = malloc(sizeof(char *)*(size_t)n);
    if (!result) return real_props->propSetStringN(h,p,n,v);
    for(int i=0;i<n;++i) result[i]=translated(v[i]);
    OfxStatus status=real_props->propSetStringN(h,p,n,result); free(result); return status;
}

static const void *fetch_suite(OfxPropertySetHandle h,const char *name,int version) {
    const void *suite=real_host->fetchSuite(h,name,version);
    if (!suite || strcmp(name,kOfxPropertySuite) || version!=1) return suite;
    AcquireSRWLockExclusive(&suite_lock);
    if (!real_props) {
        real_props=suite; bridge_props=*real_props;
        bridge_props.propSetString=set_string; bridge_props.propSetStringN=set_strings;
    }
    ReleaseSRWLockExclusive(&suite_lock);
    return &bridge_props;
}

/* Generated per-index setters preserve separate setHost callbacks in multi-effect modules. */
static void set_host_index(int index,OfxHost *host) {
    real_host=host; bridge_host=*host; bridge_host.fetchSuite=fetch_suite;
    if(originals[index] && originals[index]->setHost) originals[index]->setHost(&bridge_host);
}
#include "setters.inc"

static BOOL CALLBACK initialize(PINIT_ONCE once,void *parameter,void **context) {
    (void)once; (void)parameter; (void)context;
    wchar_t path[32768], dict[32768]; HMODULE self=NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                      (LPCWSTR)(void *)&initialize,&self);
    DWORD size=GetModuleFileNameW(self,path,32700);
    if (!size || size>=32700) return TRUE;
    wcscpy(dict,path); wcscat(dict,L".rpm-translations.tsv");
    FILE *f=_wfopen(dict,L"rb");
    if(f) {
        if(!fseek(f,0,SEEK_END)) {
            long length=ftell(f); rewind(f);
            if(length>0 && length<32*1024*1024) {
                char *buffer=calloc((size_t)length+1,1);
                if(buffer && fread(buffer,1,(size_t)length,f)==(size_t)length) {
                    size_t lines=1; for(long i=0;i<length;++i) if(buffer[i]=='\n') ++lines;
                    keys=calloc(lines,sizeof(char *)); values=calloc(lines,sizeof(char *));
                    if(keys && values) {
                        char *line=buffer;
                        while(line && *line) {
                            char *next=strchr(line,'\n'); if(next) *next++=0;
                            char *tab=strchr(line,'\t');
                            if(tab) { *tab++=0; keys[word_count]=unescape(line); values[word_count++]=unescape(tab); }
                            line=next;
                        }
                    }
                    /* buffer is process-lifetime storage for dictionary strings. */
                } else free(buffer);
            }
        }
        fclose(f);
    }
    wcscat(path,L".rpm-original");
    original_module=LoadLibraryExW(path,NULL,LOAD_WITH_ALTERED_SEARCH_PATH);
    if(original_module) {
        get_count=(void *)GetProcAddress(original_module,"OfxGetNumberOfPlugins");
        get_plugin=(void *)GetProcAddress(original_module,"OfxGetPlugin");
    }
    return TRUE;
}

__declspec(dllexport) int OfxGetNumberOfPlugins(void) {
    InitOnceExecuteOnce(&init_once,initialize,NULL,NULL);
    if(!get_count || !get_plugin) return 0;
    int count=get_count(); return count<0 || count>MAX_PLUGINS ? 0 : count;
}

__declspec(dllexport) OfxPlugin *OfxGetPlugin(int index) {
    if(index<0 || index>=OfxGetNumberOfPlugins()) return NULL;
    if(!originals[index]) {
        OfxPlugin *p=get_plugin(index); if(!p) return NULL;
        originals[index]=p; copies[index]=*p; copies[index].setHost=setters[index];
    }
    return &copies[index];
}

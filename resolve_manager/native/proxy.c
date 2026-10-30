/* OFX display-text adapter. Rendering, identifiers and values remain in the original module. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ofxCore.h"
#include "ofxProperty.h"

#define MAX_PLUGINS 512
static HMODULE original_module;
static OfxPlugin *originals[MAX_PLUGINS], copies[MAX_PLUGINS];
typedef struct HostContext {
    OfxHost real_host, bridge_host;
    OfxPropertySuiteV1 bridge_props;
    SRWLOCK lock;
    int props_ready;
} HostContext;
static HostContext hosts[MAX_PLUGINS];
typedef struct Callbacks {
    void (*set_host)(OfxHost *);
    const void *(*fetch)(OfxPropertySetHandle,const char *,int);
    OfxPluginEntryPoint *entry;
    OfxPropertySuiteV1 properties;
} Callbacks;
static void set_host_index(int,OfxHost *);
static const void *fetch_suite_index(int,OfxPropertySetHandle,const char *,int);
static OfxStatus set_string_index(int,OfxPropertySetHandle,const char *,int,const char *);
static OfxStatus set_strings_index(int,OfxPropertySetHandle,const char *,int,const char *const *);
static OfxStatus main_index(int,const char *,const void *,OfxPropertySetHandle,OfxPropertySetHandle);
static const OfxPropertySuiteV1 *current_props(int);
#include "forwarders.inc"
#include "setters.inc"
static INIT_ONCE init_once = INIT_ONCE_STATIC_INIT;
static SRWLOCK plugin_lock = SRWLOCK_INIT;
static int plugin_count;
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

static OfxStatus set_string_index(int index,OfxPropertySetHandle h,const char *p,int i,const char *v) {
    const OfxPropertySuiteV1 *props=current_props(index);
    if(!props || !props->propSetString) return kOfxStatErrMissingHostFeature;
    return props->propSetString(h,p,i,display_property(p)?translated(v):v);
}

static OfxStatus set_strings_index(int index,OfxPropertySetHandle h,const char *p,int n,const char *const *v) {
    const OfxPropertySuiteV1 *props=current_props(index);
    if(!props || !props->propSetStringN) return kOfxStatErrMissingHostFeature;
    if (!display_property(p) || n<=0 || !v) return props->propSetStringN(h,p,n,v);
    const char **result = malloc(sizeof(char *)*(size_t)n);
    if (!result) return props->propSetStringN(h,p,n,v);
    for(int i=0;i<n;++i) result[i]=translated(v[i]);
    OfxStatus status=props->propSetStringN(h,p,n,result); free(result); return status;
}

static const OfxPropertySuiteV1 *current_props(int index) {
    HostContext *ctx=&hosts[index];
    if(!ctx->real_host.fetchSuite) return NULL;
    const void *suite=ctx->real_host.fetchSuite(ctx->real_host.host,kOfxPropertySuite,1);
    return suite && suite!=&ctx->bridge_props ? suite : NULL;
}

static const void *fetch_suite_index(int index,OfxPropertySetHandle h,const char *name,int version) {
    HostContext *ctx=&hosts[index];
    if(!ctx->real_host.fetchSuite || !name) return NULL;
    const void *suite=ctx->real_host.fetchSuite(h,name,version);
    if (!suite || strcmp(name,kOfxPropertySuite) || version!=1) return suite;
    AcquireSRWLockExclusive(&ctx->lock);
    if (!ctx->props_ready) {
        if(suite==&ctx->bridge_props) { ReleaseSRWLockExclusive(&ctx->lock); return NULL; }
        /* Every callback is guarded and resolves the original suite in this effect's host. */
        ctx->bridge_props=callbacks[index].properties;
        ctx->props_ready=1;
    }
    ReleaseSRWLockExclusive(&ctx->lock);
    return &ctx->bridge_props;
}

/* Generated per-index setters preserve separate setHost callbacks in multi-effect modules. */
static void set_host_index(int index,OfxHost *host) {
    if(!host || !originals[index]) return;
    HostContext *ctx=&hosts[index];
    AcquireSRWLockExclusive(&ctx->lock);
    ctx->real_host=*host; ctx->bridge_host=*host;
    ctx->bridge_host.fetchSuite=callbacks[index].fetch;
    ctx->props_ready=0;
    ReleaseSRWLockExclusive(&ctx->lock);
    if(originals[index]->setHost) originals[index]->setHost(&ctx->bridge_host);
}

static OfxStatus main_index(int index,const char *action,const void *handle,OfxPropertySetHandle in,OfxPropertySetHandle out) {
    OfxPlugin *original=originals[index];
    if(!original || !original->mainEntry) return kOfxStatErrMissingHostFeature;
    return original->mainEntry(action,handle,in,out);
}

static BOOL CALLBACK initialize(PINIT_ONCE once,void *parameter,void **context) {
    (void)once; (void)parameter; (void)context;
    wchar_t path[32768], dict[32768]; HMODULE self=NULL;
    /* Vendor DLLs retain the returned suites across OFX scan/unload/reload cycles.
       Keep our callback code and tables alive for exactly as long as the delegated DLLs. */
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
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
        if(get_count && get_plugin) {
            int count=get_count();
            plugin_count=count>=0 && count<=MAX_PLUGINS?count:0;
        }
    }
    return TRUE;
}

__declspec(dllexport) int OfxGetNumberOfPlugins(void) {
    InitOnceExecuteOnce(&init_once,initialize,NULL,NULL);
    return plugin_count;
}

__declspec(dllexport) const char *RpmAdapterIdentity(void) { return "RPM_ADAPTER_ABI_2"; }

__declspec(dllexport) OfxPlugin *OfxGetPlugin(int index) {
    if(index<0 || index>=OfxGetNumberOfPlugins()) return NULL;
    AcquireSRWLockExclusive(&plugin_lock);
    if(!originals[index]) {
        OfxPlugin *p=get_plugin(index);
        if(!p) { ReleaseSRWLockExclusive(&plugin_lock); return NULL; }
        originals[index]=p; copies[index]=*p;
        copies[index].setHost=callbacks[index].set_host;
        copies[index].mainEntry=callbacks[index].entry;
    }
    ReleaseSRWLockExclusive(&plugin_lock);
    return &copies[index];
}

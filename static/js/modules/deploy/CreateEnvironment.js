// 新增环境组件 - 步骤：基本信息 → 确认提交 → 部署进度
const CreateEnvironment = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="steps">
        <div class="step" :class="{active:step===1,done:step>1}"><div class="step-num">1</div><div class="step-text">基本信息</div></div>
        <div class="sline" :class="{done:step>2}"></div>
        <div class="step" :class="{active:step===2,done:step>2}"><div class="step-num">2</div><div class="step-text">确认提交</div></div>
        <div class="sline" :class="{done:step>3}"></div>
        <div class="step" :class="{active:step===3}"><div class="step-num">3</div><div class="step-text">部署进度</div></div>
      </div>

      <!-- Step 1: 基本信息 -->
      <div v-if="step===1" class="page-content">
        <div class="section-title">选择项目</div>
        <div class="form-group">
          <label class="form-label">项目 *</label>
          <select class="form-input" v-model="form.projectId" @change="loadSourceEnvs"><option value="">请选择</option><option v-for="p in projects" :key="p.id" :value="p.id">[[ p.name ]]</option></select>
        </div>

        <div class="sttl">复制来源</div>
        <div class="form-group">
          <label class="form-label">从哪个环境复制？ *</label>
          <select class="form-input" v-model="form.sourceEnv" @change="loadSourceInfo"><option value="">请选择源环境</option><option v-for="e in sourceEnvs" :key="e.name" :value="e.name">[[ e.name ]]</option></select>
        </div>
        <div v-if="sourceServices.length" class="info-box">
          <div style="font-weight:bold;margin-bottom:8px">将复制的服务 ([[ sourceServices.length ]]个)</div>
          <div v-for="s in sourceServices" :key="s.name"><span class="text-primary">[[ s.name ]]</span> — [[ s.xms ]]G/[[ s.xmx ]]G, [[ s.replicas ]]副本</div>
        </div>
        <div v-if="sourceMiddleware.length" class="info-box">
          <div style="font-weight:bold;margin-bottom:8px">将复制的中间件 ([[ sourceMiddleware.length ]]个)</div>
          <div v-for="m in sourceMiddleware" :key="m"><span class="text-primary">[[ m ]]</span></div>
        </div>

        <div class="sttl">环境配置</div>
        <div class="form-group">
          <label class="form-label">环境名称 *</label>
          <div class="input-with-icon">
            <input class="form-input" v-model="form.envName" placeholder="如: dev, test, api" @blur="validateEnv">
            <span v-if="envValid===false" class="icon-success">✓</span>
            <span v-else-if="envValid===true" class="icon-warning">⚠</span>
          </div>
          <div v-if="envValid===true" class="form-hint text-warning">环境已存在，将继续覆盖</div>
        </div>

        <div class="bg2"><button class="btn btn-default" @click="resetForm">重置</button><button class="btn btn-primary" :disabled="!form.sourceEnv||!form.envName" @click="step=2">下一步</button></div>
      </div>

      <!-- Step 2: 确认 -->
      <div v-if="step===2" class="page-content">
        <div class="section-title">确认信息</div>
        <table class="summary-table"><tbody>
          <tr><td>操作类型</td><td>新增环境</td></tr>
          <tr><td>项目</td><td>[[ projectName ]]</td></tr>
          <tr><td>源环境</td><td>[[ form.sourceEnv ]]</td></tr>
          <tr><td>环境名称</td><td>[[ form.envName ]]</td></tr>
          <tr><td>域名</td><td>[[ form.envName ]].[[ domainSuffix ]]</td></tr>

          <tr><td>服务列表</td><td>[[ sourceServices.map(s=>s.name).join(', ') ]]</td></tr>
          <tr><td>中间件</td><td>[[ sourceMiddleware.join(', ') ]]</td></tr>
        </tbody></table>
        <div class="bg2"><button class="btn btn-default" @click="step=1">上一步</button><button v-if="$auth.hasPermission('op:deploy_env')" class="btn btn-success" :disabled="submitting" @click="submit">[[ submitting ? '提交中...' : '确认提交' ]]</button></div>
      </div>

      <!-- Step 3: 部署进度 -->
      <div v-if="step===3" style="display:flex;flex-direction:column;flex:1;overflow:hidden;padding:16px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <div class="section-title" style="margin:0">
            [[ deployDone ? (deploySuccess ? '部署完成' : '部署失败') : '正在部署...' ]]
          </div>
          <span style="display:flex;align-items:center;gap:8px">
            <span style="color:#909399;font-size:12px">共 [[ logs.length ]] 行</span>
            <button class="btn btn-default btn-sm" @click="copyLogs" :disabled="!logs.length" style="padding:2px 10px;font-size:12px">📋 复制日志</button>
          </span>
          <span v-if="!deployDone" class="deploy-spinner"></span>
        </div>
        <div class="deploy-log" ref="logContainer">
          <div v-for="(log, i) in logs" :key="i" :class="['log-line', 'log-'+log.level.toLowerCase()]">
            <span class="log-time">[[ log.time ]]</span>
            <span :class="['log-level', 'lvl-'+log.level.toLowerCase()]">[[ log.level ]]</span>
            <span v-if="log.step" class="log-step">[[ log.step ]]</span>
            <span class="log-msg">[[ log.message ]]</span>
          </div>
        </div>
        <div v-if="deployDone" class="bg2" style="margin-top:12px">
          <button class="btn btn-default" @click="resetAndBack">返回</button>
        </div>
      </div>
    </div>
  `,
  data(){return{
    step:1,projects:[],sourceEnvs:[],sourceServices:[],sourceMiddleware:[],
    form:{projectId:'',sourceEnv:'',envName:'',portStart:30000},
    envValid:null,domainSuffix:'hzbxhd.com',
    submitting:false,
    logs:[],deployDone:false,deploySuccess:false,eventSource:null
  }},
  computed:{
    projectName(){var p=this.projects.find(p=>p.id==this.form.projectId);return p?p.name:''}
  },
  methods:{
    loadProjects(){ajax('GET','/api/admin/projects',null,r=>{this.projects=r.data||[]})},
    loadSourceEnvs(){if(!this.form.projectId)return;ajax('GET','/api/admin/projects/'+this.form.projectId+'/environments',null,r=>{this.sourceEnvs=r.data||[];this.form.sourceEnv='';this.sourceServices=[];this.sourceMiddleware=[]})},
    loadSourceInfo(){if(!this.form.sourceEnv||!this.projectName)return;ajax('GET','/api/manage/environments/source-info?environment='+this.projectName+'-'+this.form.sourceEnv,null,r=>{if(r.code===200){this.sourceServices=r.data.services||[];this.sourceMiddleware=r.data.middleware||[]}})},
    validateEnv(){if(!this.form.envName||!this.projectName){this.envValid=null;return}ajax('GET','/api/manage/validate/environment?project='+this.projectName+'&env='+this.form.envName,null,r=>{this.envValid=r.data.exists})},
    submit(){
      this.submitting=true;
      var p={project_id:this.form.projectId,source_env:this.form.sourceEnv,env_name:this.form.envName,domain:this.projectName+this.form.envName+'.'+this.domainSuffix,debug_port:this.form.portStart,node_port:this.form.portStart+30,jmx_port:this.form.portStart+60,middleware_port:this.form.portStart+90,middleware:this.sourceMiddleware,services:this.sourceServices};
      ajax('POST','/api/deploy/execute/env',p,r=>{
        this.submitting=false;
        if(r.code===200){
          this.step=3;
          this.connectSSE(r.data.project, r.data.env);
        }else{
          showError(r.msg||'提交失败');
        }
      });
    },
    connectSSE(project, env){
      var self=this;
      self.logs=[];
      self.deployDone=false;
      self.deploySuccess=false;
      var url='/api/deploy/stream?project='+encodeURIComponent(project)+'&env='+encodeURIComponent(env)+'&action=environment';
      var token=localStorage.getItem('auth_token')||'';
      var es=new EventSource(url+'&token='+encodeURIComponent(token));
      self.eventSource=es;
      es.onmessage=function(e){
        try{
          var d=JSON.parse(e.data);
          if(d.done){
            self.deployDone=true;
            self.deploySuccess=d.success!==false;
            es.close();
            return;
          }
          self.logs.push(d);
          self.$nextTick(function(){
            var c=self.$refs.logContainer;
            if(c)c.scrollTop=c.scrollHeight;
          });
        }catch(ex){console.error('SSE parse error',ex)}
      };
      es.onerror=function(){
        self.deployDone=true;
        self.deploySuccess=false;
        self.logs.push({time:'--',level:'ERROR',message:'连接中断'});
        es.close();
      };
    },
    resetForm(){
      this.step=1;
      this.form.projectId='';this.form.sourceEnv='';this.form.envName='';
      this.sourceEnvs=[];this.sourceServices=[];this.sourceMiddleware=[];this.envValid=null;
    },
    copyLogs(){
      var lines=this.logs.map(function(l){
        return (l.time||'')+' '+(l.level||'')+(l.step?' ['+l.step+']':'')+' '+(l.message||'')+'\n';
      }).join('');
      if(!lines)return;
      var header='['+this.projectName+'-'+this.form.envName+'] 新增环境部署日志\n\n';
      var text=header+lines;
      if(navigator.clipboard&&window.isSecureContext){
        navigator.clipboard.writeText(text).then(function(){showSuccess('日志已复制到剪贴板')}).catch(function(){fallbackCopy(text)});
      }else{
        fallbackCopy(text);
      }
      function fallbackCopy(str){
        var ta=document.createElement('textarea');
        ta.value=str;ta.style.position='fixed';ta.style.opacity='0';
        document.body.appendChild(ta);ta.select();
        try{document.execCommand('copy');showSuccess('日志已复制到剪贴板');}
        catch(e){showError('复制失败');}
        document.body.removeChild(ta);
      }
    },
    resetAndBack(){
      this.step=1;
      this.logs=[];
      this.deployDone=false;
      this.deploySuccess=false;
      if(this.eventSource){this.eventSource.close();this.eventSource=null}
    }
  },
  created(){
    this.loadProjects();
    ajax('GET','/api/settings/list',null,r=>{this.domainSuffix=r.data?.default_domain?.value||'hzbxhd.com'});
    ajax('GET','/api/manage/environments/available-port',null,r=>{
      if(r.code===200&&r.data.available_port){this.form.portStart=r.data.available_port}
    });
  },
  beforeUnmount(){
    if(this.eventSource){this.eventSource.close();this.eventSource=null}
  }
};

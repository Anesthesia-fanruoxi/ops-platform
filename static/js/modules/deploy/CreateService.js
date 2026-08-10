// 新增服务组件 - 步骤：添加服务 → 确认提交 → 部署进度
const CreateService = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="steps">
        <div class="step" :class="{active:step===1,done:step>1}"><div class="step-num">1</div><div class="step-text">添加服务</div></div>
        <div class="sline" :class="{done:step>2}"></div>
        <div class="step" :class="{active:step===2,done:step>2}"><div class="step-num">2</div><div class="step-text">确认提交</div></div>
        <div class="sline" :class="{done:step>3}"></div>
        <div class="step" :class="{active:step===3}"><div class="step-num">3</div><div class="step-text">部署进度</div></div>
      </div>

      <!-- Step 1: 添加服务 -->
      <div v-if="step===1" class="page-content">
        <div class="section-title">选择项目和环境</div>
        <div class="fr">
          <div class="form-group">
            <label class="form-label">项目 *</label>
            <select class="form-input" v-model="form.projectId" @change="loadEnvs"><option value="">请选择</option><option v-for="p in projects" :key="p.id" :value="p.id">[[ p.name ]]</option></select>
          </div>
          <div class="form-group">
            <label class="form-label">环境 *</label>
            <select class="form-input" v-model="form.envId"><option value="">请选择环境</option><option v-for="e in envs" :key="e.id" :value="e.id">[[ e.name ]] ([[ e.domain ]])</option></select>
          </div>
        </div>

        <div class="sttl">服务配置</div>
        <div class="form-group">
          <label class="form-label">服务名称 *</label>
          <div class="input-with-icon">
            <input class="form-input" v-model="form.name" placeholder="如: app, gateway" @blur="validateService">
            <span v-if="svcValid===false" class="icon-success">✓</span>
            <span v-else-if="svcValid===true" class="icon-warning">⚠</span>
          </div>
          <div v-if="svcValid===true" class="form-hint text-warning">该服务已存在</div>
        </div>
        <div class="fr">
          <div class="form-group"><label class="form-label">JVM最小内存 (G)</label><input class="form-input" type="number" v-model.number="form.xms" value="2"></div>
          <div class="form-group"><label class="form-label">JVM最大内存 (G)</label><input class="form-input" type="number" v-model.number="form.xmx" value="8"></div>
        </div>
        <div class="form-group"><label class="form-label">副本数</label><input class="form-input" type="number" v-model.number="form.replicas" value="1" style="width:150px"></div>
        <div class="bg2"><button class="btn btn-default" @click="resetForm">重置</button><button class="btn btn-primary" :disabled="!form.name||!form.projectId||!form.envId" @click="step=2">下一步</button></div>
      </div>

      <!-- Step 2: 确认 -->
      <div v-if="step===2" class="page-content">
        <div class="section-title">确认信息</div>
        <table class="summary-table"><tbody>
          <tr><td>操作类型</td><td>新增服务</td></tr>
          <tr><td>项目</td><td>[[ projectName ]]</td></tr>
          <tr><td>环境</td><td>[[ envName ]]</td></tr>
          <tr><td>服务名称</td><td>[[ form.name ]]</td></tr>
          <tr><td>JVM</td><td>[[ form.xms ]]G/[[ form.xmx ]]G</td></tr>
          <tr><td>副本数</td><td>[[ form.replicas ]]</td></tr>
        </tbody></table>
        <div class="bg2"><button class="btn btn-default" @click="step=1">上一步</button><button class="btn btn-success" :disabled="submitting" @click="submit">[[ submitting ? '提交中...' : '🚀 确认提交' ]]</button></div>
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
  data(){return{step:1,projects:[],envs:[],form:{projectId:'',envId:'',name:'',xms:2,xmx:8,replicas:1},svcValid:null,submitting:false,logs:[],deployDone:false,deploySuccess:false,eventSource:null}},
  computed:{
    projectName(){var p=this.projects.find(p=>p.id==this.form.projectId);return p?p.name:''},
    envName(){var e=this.envs.find(e=>e.id==this.form.envId);return e?e.name:''}
  },
  methods:{
    loadProjects(){ajax('GET','/api/admin/projects',null,r=>{this.projects=r.data||[]})},
    loadEnvs(){if(!this.form.projectId)return;ajax('GET',`/api/admin/projects/${this.form.projectId}/environments`,null,r=>{this.envs=r.data||[];this.form.envId=''})},
    validateService(){if(!this.form.name||!this.projectName||!this.envName){this.svcValid=null;return}ajax('GET',`/api/manage/validate/service?name=${this.form.name}&project=${this.projectName}&env=${this.envName}`,null,r=>{this.svcValid=r.data.exists})},
    resetForm(){this.step=1;this.form={projectId:'',envId:'',name:'',xms:2,xmx:8,replicas:1};this.svcValid=null;this.envs=[]},
    submit(){
      this.submitting=true;
      var p={action:'create_service',project_id:this.form.projectId,environment_id:this.form.envId,services:[{name:this.form.name,xms:this.form.xms,xmx:this.form.xmx,replicas:this.form.replicas}]};
      var self=this;
      ajax('POST','/api/deploy/execute',p,r=>{
        self.submitting=false;
        if(r.code===200){
          self.step=3;
          self.connectSSE(r.data.project, r.data.env);
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
      var url='/api/deploy/stream?project='+encodeURIComponent(project)+'&env='+encodeURIComponent(env)+'&action=create_service';
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
    copyLogs(){
      var lines=this.logs.map(function(l){
        return (l.time||'')+' '+(l.level||'')+(l.step?' ['+l.step+']':'')+' '+(l.message||'')+'\n';
      }).join('');
      if(!lines)return;
      var header='['+this.projectName+'-'+this.envName+'] 新增服务部署日志\n\n';
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
  created(){this.loadProjects()},
  beforeUnmount(){
    if(this.eventSource){this.eventSource.close();this.eventSource=null}
  }
};

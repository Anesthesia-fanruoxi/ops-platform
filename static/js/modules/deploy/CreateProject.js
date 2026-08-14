// 新增项目组件 - 步骤：基本信息 → 服务列表 → 中间件 → 确认提交
const CreateProject = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="steps">
        <div class="step" :class="{active:step===1,done:step>1}"><div class="step-num">1</div><div class="step-text">基本信息</div></div>
        <div class="sline" :class="{done:step>2}"></div>
        <div class="step" :class="{active:step===2,done:step>2}"><div class="step-num">2</div><div class="step-text">服务列表</div></div>
        <div class="sline" :class="{done:step>3}"></div>
        <div class="step" :class="{active:step===3,done:step>3}"><div class="step-num">3</div><div class="step-text">中间件</div></div>
        <div class="sline" :class="{done:step>4}"></div>
        <div class="step" :class="{active:step===4}"><div class="step-num">4</div><div class="step-text">确认提交</div></div>
      </div>

      <!-- Step 1: 基本信息 -->
      <div v-if="step===1" class="page-content">
        <div class="section-title">项目信息</div>
        <div class="form-group">
          <label class="form-label">项目名称 *</label>
          <div class="input-with-icon">
            <input class="form-input" v-model="form.name" placeholder="如: ysh" @blur="validateProject">
            <span v-if="projectValid===false" class="icon-success">✓</span>
            <span v-else-if="projectValid===true" class="icon-warning">⚠</span>
          </div>
          <div v-if="projectValid===true" class="form-hint text-warning">项目已存在，将进入环境配置</div>
        </div>
        <div class="form-group"><label class="form-label">项目描述</label><input class="form-input" v-model="form.desc" placeholder="如: 云商汇项目"></div>
        <div class="section-title" style="margin-top:20px">环境信息</div>
        <div class="form-group"><label class="form-label">环境名称 *</label><input class="form-input" v-model="form.envName" placeholder="如: dev、test、uat"></div>
        <div class="bg2"><button class="btn btn-default" @click="resetForm">重置</button><button class="btn btn-primary" @click="next">下一步</button></div>
      </div>

      <!-- Step 2: 服务列表 -->
      <div v-if="step===2" class="page-content">
        <div class="section-title">服务列表</div>
        <div class="svc-hd"><div>服务名称</div><div>xms</div><div>xmx</div><div>副本</div><div></div></div>
        <div v-for="(s,i) in form.services" :key="i" class="svc-row">
          <input v-model="s.name" placeholder="服务名称">
          <input type="number" v-model.number="s.xms">
          <input type="number" v-model.number="s.xmx">
          <input type="number" v-model.number="s.replicas">
          <button class="btn bg" @click="form.services.splice(i,1)">删除</button>
        </div>
        <button class="btn bd" @click="addSvc" style="margin-top:8px">+ 添加服务</button>
        <div class="bg2"><button class="btn btn-default" @click="step=1">上一步</button><button class="btn btn-primary" @click="step=3">下一步</button></div>
      </div>

      <!-- Step 3: 中间件 -->
      <div v-if="step===3" class="page-content">
        <div class="section-title">选择中间件</div>
        <div class="mw-grid">
          <div v-for="mw in allMw" :key="mw.id" :class="['mw-item',{selected:mwSelected.includes(mw.id)}]" @click="toggleMw(mw.id)">
            <div class="mw-icon">[[ mw.icon ]]</div><div class="mw-name">[[ mw.name ]]</div>
          </div>
        </div>
        <div class="bg2"><button class="btn btn-default" @click="step=2">上一步</button><button class="btn btn-success" @click="step=4">下一步</button></div>
      </div>

      <!-- Step 4: 确认提交 -->
      <div v-if="step===4" class="page-content">
        <div class="section-title">确认信息</div>
        <table class="summary-table"><tbody>
          <tr><td>操作类型</td><td>新增项目</td></tr>
          <tr><td>项目名称</td><td>[[ form.name ]]</td></tr>
          <tr><td>项目描述</td><td>[[ form.desc || '-' ]]</td></tr>
          <tr><td>环境名称</td><td>[[ form.envName ]]</td></tr>
          <tr><td>域名</td><td>[[ form.envName ]].[[ domainSuffix ]]</td></tr>

          <tr><td>端口</td><td>D:[[ portStart ]] N:[[ portStart+30 ]] J:[[ portStart+60 ]] M:[[ portStart+90 ]]</td></tr>
          <tr><td>中间件</td><td>[[ mwSelected.join(', ') ]]</td></tr>
          <tr><td>服务列表</td><td>[[ form.services.map(s=>s.name).join(', ') ]]</td></tr>
        </tbody></table>
        <div class="bg2"><button class="btn btn-default" @click="step=3">上一步</button><button v-if="$auth.hasPermission('op:deploy_project')" class="btn btn-success" @click="submit">🚀 确认提交</button></div>
      </div>

      <!-- 部署进度弹框 -->
      <div v-if="progressVisible" class="dialog-overlay" @click.self="closeProgress">
        <div class="dialog progress-dialog">
          <div class="dialog-header" @mousedown="startDrag">
            <span class="dialog-title">[[ progressDone ? (progressSuccess ? '✅' : '❌') : '⏳' ]] 部署进度 - [[ form.name ]]-[[ form.envName ]]
              <span class="log-count">共 [[ progressLogs.length ]] 行</span>
            </span>
            <span style="display:flex;align-items:center;gap:8px">
              <button class="btn btn-default btn-sm" @click.stop="copyLogs" :disabled="!progressLogs.length" style="padding:2px 10px;font-size:12px">📋 复制日志</button>
              <button class="dialog-close" @click="closeProgress">✕</button>
            </span>
          </div>
          <div class="deploy-log" ref="progressLogContainer">
            <div v-for="(log,i) in progressLogs" :key="i" :class="'log-line log-'+(log.level||'info').toLowerCase()">
              <span class="log-time">[[ log.time || '' ]]</span>
              <span :class="'log-level lvl-'+(log.level||'info').toLowerCase()">[[ log.level || 'INFO' ]]</span>
              <span v-if="log.step" class="log-step">[[ log.step ]]</span>
              <span class="log-msg">[[ log.message || log.msg || '' ]]</span>
            </div>
            <div v-if="progressDone" :class="'log-line log-'+(progressSuccess?'done':'error')">
              <span class="log-msg">[[ progressSuccess ? '=== 部署完成 ===' : '=== 部署失败 ===' ]]</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  data(){return{step:1,steps:['基本信息','服务列表','中间件','确认提交'],form:{name:'',desc:'',envName:'',portStart:30000,services:[]},projectValid:null,envValid:null,settings:{},domainSuffix:'hzbxhd.com',allMw:[{id:'nacos',name:'Nacos',icon:'📡'},{id:'mysql-nfs',name:'MySQL-NFS',icon:'🗄️'},{id:'redis',name:'Redis',icon:'🔴'},{id:'mysql',name:'MySQL',icon:'🐬'},{id:'rabbitmq',name:'RabbitMQ',icon:'🐰'},{id:'kafka',name:'Kafka',icon:'📨'}],mwSelected:['nacos','mysql-nfs','redis','mysql','rabbitmq'],progressVisible:false,progressLogs:[],progressDone:false,progressSuccess:false,eventSource:null,dragX:0,dragY:0,dragging:false,dragOffX:0,dragOffY:0}},
  computed:{portStart(){return this.form.portStart}},
  methods:{
    addSvc(){this.form.services.push({name:'',xms:2,xmx:8,replicas:1})},
    toggleMw(id){var i=this.mwSelected.indexOf(id);if(i>=0)this.mwSelected.splice(i,1);else this.mwSelected.push(id)},
    validateProject(){if(!this.form.name){this.projectValid=null;return}ajax('GET',`/api/manage/validate/project?name=${this.form.name}`,null,r=>{this.projectValid=r.data.exists})},
    next(){if(this.step===1&&!this.form.name){showWarning('请输入项目名称');return}this.step++},
    resetForm(){this.step=1;this.form={name:'',desc:'',envName:'',portStart:this.form.portStart,services:[]};this.projectValid=null;this.mwSelected=['nacos','mysql-nfs','redis','mysql','rabbitmq']},
    submit(){
      if(!this.form.name||!this.form.envName){showWarning('请输入项目名称和环境名称');return}
      var p={project_name:this.form.name,project_desc:this.form.desc,env_name:this.form.envName,domain:this.form.name+this.form.envName+'.'+this.domainSuffix,debug_port:this.form.portStart,node_port:this.form.portStart+30,jmx_port:this.form.portStart+60,middleware_port:this.form.portStart+90,middleware:this.mwSelected,services:this.form.services.filter(s=>s.name)};
      ajax('POST','/api/deploy/execute/project',p,r=>{
        if(r.code===200){this.openProgress();}
        else showError(r.msg||'提交失败');
      });
    },
    openProgress(){
      this.progressVisible=true;this.progressLogs=[];this.progressDone=false;this.progressSuccess=false;this.dragX=0;this.dragY=0;
      this.connectSSE();
    },
    connectSSE(){
      var self=this;
      var url='/api/deploy/stream?project='+encodeURIComponent(this.form.name)+'&env='+encodeURIComponent(this.form.envName)+'&action=create_project';
      var token=localStorage.getItem('auth_token')||'';
      var es=new EventSource(url+'&token='+encodeURIComponent(token));
      self.eventSource=es;
      es.onmessage=function(e){
        try{
          var d=JSON.parse(e.data);
          if(d.done){self.progressDone=true;self.progressSuccess=d.success!==false;es.close();self.eventSource=null;return;}
          self.progressLogs.push(d);
          self.$nextTick(function(){var c=self.$refs.progressLogContainer;if(c)c.scrollTop=c.scrollHeight;});
        }catch(ex){}
      };
      es.onerror=function(){es.close();self.eventSource=null;};
    },
    closeProgress(){
      this.progressVisible=false;
      if(this.eventSource){this.eventSource.close();this.eventSource=null;}
    },
    copyLogs(){
      var lines=this.progressLogs.map(function(l){
        return (l.time||'')+' '+(l.level||'')+(l.step?' ['+l.step+']':'')+' '+(l.message||l.msg||'')+'\n';
      }).join('');
      if(!lines)return;
      var header='['+this.form.name+'-'+this.form.envName+'] 新增项目部署日志\n\n';
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
    startDrag(e){
      this.dragging=true;
      var rect=e.currentTarget.parentElement.getBoundingClientRect();
      this.dragOffX=e.clientX-rect.left;this.dragOffY=e.clientY-rect.top;
      if(!this.dragX){this.dragX=rect.left;this.dragY=rect.top;}
      document.addEventListener('mousemove',this.onDrag);
      document.addEventListener('mouseup',this.endDrag);
    },
    onDrag(e){if(!this.dragging)return;this.dragX=e.clientX-this.dragOffX;this.dragY=e.clientY-this.dragOffY;},
    endDrag(){this.dragging=false;document.removeEventListener('mousemove',this.onDrag);document.removeEventListener('mouseup',this.endDrag);}
  },
  created(){
    ajax('GET','/api/settings/list',null,r=>{this.settings=r.data||{};this.domainSuffix=r.data?.default_domain?.value||'hzbxhd.com'});
    ajax('GET','/api/manage/environments/available-port',null,r=>{
      if(r.code===200&&r.data.available_port){this.form.portStart=r.data.available_port}
    });
  }
};

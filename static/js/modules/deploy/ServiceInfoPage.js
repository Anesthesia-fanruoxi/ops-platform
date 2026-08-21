// ============================================================
// 服务信息页面
// - 选项目 + 环境 → 展示该环境各服务（deployment YAML + k8s Pod 状态）
// - 运行日志：SSE 实时流（先回放历史，再 follow 跟随）
// - Nacos 配置：列出/查看/修改 namespace 下配置（Nacos Open API）
// - 部署配置：deployment YAML 原文
// ============================================================

const ServiceInfoPage = {
  name: 'ServiceInfoPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="serviceinfo-layout">
  <aside class="serviceinfo-favbar" :class="{ collapsed: favCollapsed }">
    <div class="serviceinfo-favhead">
      <span class="serviceinfo-favtitle">环境收藏</span>
      <el-button link size="small" class="serviceinfo-favtoggle" @click="toggleFavBar">[[ favCollapsed ? '»' : '«' ]]</el-button>
    </div>
    <div class="serviceinfo-favlist" v-if="!favCollapsed">
      <div v-if="!favorites.length" class="serviceinfo-favempty">暂无收藏，选好环境后点「收藏此环境」</div>
      <div v-for="f in favorites" :key="f.id" class="serviceinfo-favcard"
           :class="{ 'is-active': f.project_name === selectedProject && f.env_name === selectedEnv }"
           @click="selectFavorite(f)">
        <div class="serviceinfo-favmain">
          <div class="serviceinfo-favproj">[[ f.project_name ]]</div>
          <div class="serviceinfo-favenv"><span class="serviceinfo-favdot">●</span> [[ f.env_name ]]</div>
        </div>
        <el-button link size="small" class="serviceinfo-favdel" @click.stop="removeFavorite(f.id)">✕</el-button>
      </div>
    </div>
  </aside>
  <div class="serviceinfo-main">
  <div class="toolbar" style="display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
    <el-select v-model="selectedProject" placeholder="选择项目" size="default" style="width:180px;"
               @change="onProjectChange" filterable>
      <el-option v-for="p in projects" :key="p" :label="p" :value="p"></el-option>
    </el-select>
    <el-select v-model="selectedEnv" placeholder="选择环境" size="default" style="width:160px;"
               @change="loadServices" :disabled="!selectedProject" filterable>
      <el-option v-for="e in envs" :key="e" :label="e" :value="e"></el-option>
    </el-select>
    <!-- SSE 实时推送无需手动刷新；仅当 SSE 回退/K8s 不可用（k8sError）时提供「重新连接」入口 -->
    <el-button v-if="k8sError" type="warning" plain @click="loadServices">重新连接</el-button>
    <!-- 未选择环境时不显示（避免不可用按钮占位） -->
    <el-button v-if="selectedProject && selectedEnv" type="primary" plain @click="openGlobalNacos">全局 Nacos 配置</el-button>
    <el-button v-if="selectedProject && selectedEnv && canDeploy" type="success" plain
               @click="openDeploy">🚀 快捷部署</el-button>
    <!-- 运行状态：监听环境构建 SSE（5s 一帧）；SSE 无任务 → 暂无构建任务，有任务 → 构建中 + 当前步骤 -->
    <span v-if="selectedEnv" class="svc-run-status" :class="{ 'svc-run-active': !!activeBuild }"
          :title="activeBuild ? ('点击查看构建步骤 ' + activeBuild.build_no) : ''"
          @click="activeBuild && openProgressDrawer(activeBuild)">
      <template v-if="activeBuild">
        <span class="svc-active-dot"></span>
        <span class="svc-run-text">构建中<span v-if="activeBuild.current_step">，当前步骤：[[ activeBuild.current_step ]]</span></span>
      </template>
      <template v-else>
        <span class="svc-run-idle">暂无构建任务</span>
      </template>
    </span>
    <!-- 最近构建记录：执行人 / 执行分支 / 执行时间（靠右，点击打开进度） -->
    <span v-if="lastBuild" class="svc-toolbar-lastbuild" :title="'最近构建 ' + lastBuild.build_no"
          @click="openProgressDrawer({ id: lastBuild.id, build_no: lastBuild.build_no, status: lastBuild.status, project_type: lastBuild.project_type, branch: lastBuild.branch })">
      <span class="svc-lb-label">最近构建</span>
      <span class="svc-lb-user">[[ lastBuild.triggered_by || '-' ]]</span>
      <span class="svc-lb-branch">[[ lastBuild.branch || '-' ]]</span>
      <span class="svc-lb-time">[[ lastBuild.created_at || '' ]]</span>
    </span>
    <el-button v-if="selectedProject && selectedEnv" type="primary" plain size="small" @click="addFavorite">★ 收藏此环境</el-button>
  </div>

  <!-- 工具栏与内容区之间的虚线分割线 -->
  <div class="svc-toolbar-divider"></div>

  <!-- 快捷部署弹窗（与环境信息页构建弹窗一致：分支/最近使用/服务范围/类型） -->
  <el-dialog v-model="buildDialogVisible" :title="'构建' + (buildType === 'frontend' ? '前端' : '后端') + ' - ' + (selectedProject || '') + '-' + (selectedEnv || '')"
             width="810px" top="10vh" class="build-dialog" :close-on-click-modal="false">
    <div class="build-two-col">
      <!-- 左栏：分支 -->
      <div class="build-col">
        <div class="build-col-head">
          <span class="build-col-title">分支</span>
          <el-radio-group v-model="buildType" size="small" @change="onDeployTypeChange">
            <el-radio-button value="backend">后端</el-radio-button>
            <el-radio-button value="frontend">前端</el-radio-button>
          </el-radio-group>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <el-switch v-model="branchTreeMode" size="small" active-text="按目录展示" />
          <span style="color:#c0c4cc;font-size:12px">共 [[ branchOptions.length ]] 个分支</span>
        </div>
        <!-- 平铺模式：输入框选择/过滤 + 直接展示全部分支（最近构建分支置顶） -->
        <div v-if="!branchTreeMode" class="svc-branch-pane">
          <el-input v-model="branchSearch"
                    :placeholder="'默认分支：' + buildBranch" clearable size="small"
                    @keyup.enter="applyBranchInput" @focus="onBranchFocus" style="margin-bottom:6px" />
          <div class="svc-branch-list">
            <div v-if="branchLoading" class="svc-col-loading">加载分支中...</div>
            <div v-else>
              <!-- 最近分支分组（无最近分支则不显示该分组，直接全部分支） -->
              <template v-if="branchRecentList.length">
                <div class="svc-branch-group">最近分支</div>
                <div v-for="b in branchRecentList" :key="'r-' + b" class="svc-branch-item"
                     :class="{ active: buildBranch === b }" @click="buildBranch = b" :title="b">
                  <span class="svc-branch-recent-tag">最近</span>[[ b ]]
                </div>
              </template>
              <div v-if="branchAllList.length" class="svc-branch-group">全部分支</div>
              <div v-for="b in branchAllList" :key="'a-' + b" class="svc-branch-item"
                   :class="{ active: buildBranch === b }" @click="buildBranch = b" :title="b">[[ b ]]</div>
              <div v-if="!branchRecentList.length && !branchAllList.length" class="svc-col-empty">无匹配分支</div>
            </div>
          </div>
        </div>
        <!-- 目录树模式：直接展示层级树（异步加载，超出滚动） -->
        <div v-else class="svc-branch-tree">
          <el-input v-model="branchTreeFilter" placeholder="搜索分支" clearable size="small" style="margin-bottom:6px" />
          <div v-if="branchLoading" class="svc-col-loading">加载分支中...</div>
          <el-tree v-else :data="branchTree" node-key="key" :props="{ label: 'label', children: 'children' }"
                   highlight-current :filter-node-method="filterBranchTree" ref="branchTreeRef"
                   @node-click="onBranchNodeClick">
            <template #default="{ data }">
              <span v-if="data.isBranch" style="font-family:monospace;font-size:13px">[[ data.branch ]]</span>
              <span v-else style="font-weight:500;color:#303133">[[ data.label ]]</span>
            </template>
          </el-tree>
        </div>
      </div>
      <!-- 右栏：构建范围 -->
      <div class="build-col">
        <div class="build-col-head">
          <span class="build-col-title">构建范围</span>
          <span v-if="buildType === 'backend'" style="color:#909399;font-size:12px">全部勾选</span>
        </div>
        <template v-if="buildType === 'backend'">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
            <span style="color:#606266;font-size:13px">已选 [[ selectedServiceCount ]] / [[ serviceOptions.length ]] 个服务</span>
            <el-switch :model-value="allServicesChecked" @change="toggleAllServices" active-text="全部勾选" size="small" />
          </div>
          <div class="svc-service-list">
            <div v-if="!serviceOptions.length" class="svc-col-loading">[[ servicesLoaded ? '暂未配置服务' : '加载服务中...' ]]</div>
            <div v-for="s in serviceOptions" :key="s" class="svc-service-item">
              <span style="font-family:monospace;font-size:13px">[[ s ]]</span>
              <el-switch v-model="serviceToggles[s]" size="small" />
            </div>
          </div>
          <div style="color:#c0c4cc;font-size:11.5px;margin-top:8px">仅对开启的服务执行产物收集 / Docker Build / Push，未开启的服务自动跳过</div>
        </template>
        <div v-else style="color:#909399;font-size:12px;padding:60px 0;text-align:center">
          前端构建固定 dist 产物，无服务范围选择
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="buildDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="buildTriggering" @click="executeBuild">触发构建</el-button>
    </template>
  </el-dialog>

  <!-- 构建进度抽屉（与环境信息页一致：步骤条 + 实时日志） -->
  <el-drawer v-model="bpDrawerVisible" :title="'构建进度 - ' + (bpBuild?.build_no || '')" size="65%" class="bp-drawer" @close="closeProgressDrawer">
    <template #header>
      <div style="display:flex;align-items:center;gap:12px;width:100%">
        <span style="font-weight:600;font-size:15px">[[ bpBuild?.build_no || '' ]]</span>
        <el-tag :type="bpStatusType(bpBuild?.status)" size="small">[[ bpStatusText(bpBuild?.status) ]]</el-tag>
        <span style="flex:1"></span>
        <el-button v-if="bpBuild && bpDeployWaiting" type="warning" size="small" plain @click="openSelectDirsDialog">配置服务目录</el-button>
        <el-button v-if="bpBuild && ['running', 'pending'].includes(bpBuild.status)"
                   type="danger" size="small" plain @click="cancelBuild">取消构建</el-button>
        <el-dropdown v-if="bpBuild && ['success', 'failed', 'cancelled'].includes(bpBuild.status) && bpSteps.length"
                     @command="rerunFromStep">
          <el-button type="warning" size="small" plain>从指定步骤重跑 ▾</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="s in bpSteps" :key="s.step_no" :command="s.step_no">从「[[ s.name ]]」重跑</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </template>
    <el-steps align-center style="margin-bottom:20px">
      <el-step :status="bpLogMode === 'all' ? 'process' : 'wait'" :class="{ 'bp-step-selected': bpLogMode === 'all' }" @click="switchBpLogAll">
        <template #icon><span class="bp-step-overview">☰</span></template>
        <template #title>总览</template>
      </el-step>
      <el-step v-for="s in bpSteps" :key="s.step_no" :status="bpStepStatus(s)"
               :class="{ 'bp-step-selected': bpLogMode === bpStepType(s.step_no) }" @click="switchBpLog(s.step_no)">
        <template #title>
          <span>[[ s.name ]]</span>
          <span v-if="s.status === 'running' && s.started_at" style="font-size:12px;color:#e6a23c;margin-left:6px;font-family:monospace">⏱ [[ bpStepDuration(s) ]]</span>
          <span v-else-if="s.duration" style="font-size:12px;color:#909399;margin-left:6px;font-family:monospace">[[ bpStepDuration(s) ]]</span>
        </template>
      </el-step>
    </el-steps>
    <el-alert v-if="bpBuild && bpBuild.status === 'failed' && bpBuild.error_msg"
              :title="bpBuild.error_msg" type="error" :closable="false" show-icon style="margin-bottom:12px" />
    <div ref="bpLogContainer" class="bp-log-box">[[ bpLogView() || '等待日志输出...' ]]</div>
  </el-drawer>

  <el-alert v-if="k8sError" type="warning" :closable="false" style="margin-bottom:12px;"
            :title="'K8s 状态不可用：' + k8sError"></el-alert>


  <div class="svc-card-grid" v-loading="loading">
    <div v-if="!selectedProject || !selectedEnv" class="svc-empty svc-empty-hint">
      <div class="svc-empty-icon">📁</div>
      <div class="svc-empty-text">请先选择一个环境来查看内容</div>
      <div class="svc-empty-sub">或从左侧收藏栏中选择一个已收藏的环境</div>
    </div>
    <div v-else-if="!services.length && !loading" class="svc-empty">
      <span style="color:#909399;font-size:13px">暂无服务（该环境未生成部署配置）</span>
    </div>
    <div v-for="svc in services" :key="svc.name" class="svc-card">
      <div class="svc-card-head">
        <span class="svc-card-name" :title="svc.name">[[ svc.name ]]</span>
        <span class="svc-card-replicas" title="副本数">×[[ svc.replicas ]]</span>
        <span class="svc-card-dot" :class="svcCardDotClass(svc)" :title="svcCardDotTitle(svc)"></span>
      </div>
      <div class="svc-card-row">
        <span class="svc-card-label">镜像</span>
        <span class="svc-card-value svc-card-image" :title="svcImageTitle(svc)">[[ svc.image || '-' ]]<el-tag v-if="svc.images && svc.images.length > 1" size="small" type="info" style="margin-left:4px;vertical-align:middle" :title="svc.images.join('\\n')">×[[ svc.images.length ]]</el-tag></span>
      </div>
      <div class="svc-card-row">
        <span class="svc-card-label">端口</span>
        <span class="svc-card-value">
          <template v-if="svc.ports && svc.ports.length">
            <el-tag v-for="p in svc.ports" :key="p.label + ':' + p.port" size="small"
                    :type="p.label === 'debug' ? 'warning' : 'primary'" style="margin:0 4px 2px 0">
              [[ p.label + ':' + p.port ]]
            </el-tag>
          </template>
          <span v-else style="color:#999">-</span>
        </span>
      </div>
      <div class="svc-card-row">
        <span class="svc-card-label">状态</span>
        <span class="svc-card-value">
          <template v-if="svc.pods && svc.pods.length">
            <el-tag v-for="pod in svc.pods" :key="pod.name" size="small"
                    :type="podTagType(pod)" style="margin:2px 4px 2px 0;cursor:pointer;"
                    :title="pod.name + '（点击看日志）'" @click="openLog(svc, pod)">
              [[ podStatusText(pod) ]][[ pod.restarts ? ' ⟳' + pod.restarts : '' ]]
            </el-tag>
          </template>
          <span v-else style="color:#999">-</span>
        </span>
      </div>
      <div class="svc-card-actions">
        <el-button link type="primary" size="small" @click="openLog(svc)">日志</el-button>
        <el-button link type="primary" size="small" @click="openLogFiles(svc)">日志目录</el-button>
        <el-button link type="primary" size="small" @click="openNacos(svc)">Nacos配置</el-button>
        <el-button link type="primary" size="small" @click="openEnv(svc)">环境变量</el-button>
      </div>
    </div>
  </div>

  <!-- 运行日志弹窗（SSE 终端式；支持全屏，ESC 退出全屏） -->
  <el-dialog v-model="logVisible" width="80%" top="10vh"
             class="svc-log-dialog" :close-on-click-modal="false" :close-on-press-escape="!logFullscreen"
             :fullscreen="logFullscreen" :class="{ 'svc-log-fs': logFullscreen }" @close="onLogDialogClose">
    <template #header>
      <div class="svc-log-header">
        <span class="svc-log-title">运行日志 - [[ logServiceName ]]</span>
        <span class="svc-log-count">共 [[ logLines.length ]] 行</span>
        <el-select v-model="logTail" size="small" style="width:120px;" popper-class="svc-log-popper" @change="connectLogStream">
          <el-option :value="200" label="最近 200 行"></el-option>
          <el-option :value="500" label="最近 500 行"></el-option>
          <el-option :value="1000" label="最近 1000 行"></el-option>
        </el-select>
        <span class="svc-log-status">
          <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: streamConnected ? '#67c23a' : (logPaused ? '#e6a23c' : '#f56c6c') }"></span>
          [[ streamConnected ? '实时跟随中' : (logPaused ? '已暂停追踪' : '未连接') ]]
        </span>
        <span class="svc-log-header-tools">
          <el-input v-model="logSearchWord" ref="logSearch" size="small" style="width:200px;" clearable
                    placeholder="搜索（Ctrl+F）" @input="updateLogSearch" @keydown.enter="logSearchJump(1)">
            <template #prefix><span style="font-size:13px">🔍</span></template>
          </el-input>
          <span v-if="logSearchWord" style="color:#a8bcc0;font-size:12px;white-space:nowrap">[[ logSearchMatches.length ? (logSearchIdx + 1) + '/' + logSearchMatches.length : '无匹配' ]]</span>
          <el-button v-if="logSearchWord" size="small" :disabled="!logSearchMatches.length" @click="logSearchJump(-1)">↑</el-button>
          <el-button v-if="logSearchWord" size="small" :disabled="!logSearchMatches.length" @click="logSearchJump(1)">↓</el-button>
          <span v-if="logFullscreen" class="svc-log-fs-tip">按 ESC 退出全屏</span>
          <el-button size="small" @click="toggleLogFullscreen">[[ logFullscreen ? '退出全屏' : '⛶ 全屏' ]]</el-button>
          <el-button size="small" :type="logPaused ? 'warning' : ''" @click="toggleLogPause">[[ logPaused ? '▶ 恢复追踪' : '⏸ 暂停追踪' ]]</el-button>
          <el-button size="small" @click="connectLogStream">重连</el-button>
          <el-button size="small" plain @click="clearLogScreen">清屏</el-button>
        </span>
      </div>
    </template>
    <div class="svc-log-terminal" ref="logBox"><div v-for="(line, i) in logLines" :key="i" :id="'logline-' + i" :class="{ 'svc-log-match': isLogMatch(i) }" v-html="highlightLogLine(line)"></div></div>
  </el-dialog>

  <!-- 环境变量弹窗 -->
  <el-dialog v-model="envVisible" :title="'环境变量 - ' + (envServiceName || '')" width="85%" top="10vh">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
      <el-input v-model="envSearchWord" size="small" style="width:300px;" clearable
                placeholder="搜索变量名（子序列匹配，忽略符号/大小写）" @input="envSearchWord = envSearchWord">
        <template #prefix><span style="font-size:13px">🔍</span></template>
      </el-input>
      <span style="color:#909399;font-size:12px">共 [[ envRows.length ]] 个变量[[ envSearchWord ? '，匹配 ' + filteredEnvRows.length + ' 个' : '' ]]</span>
    </div>
    <el-table :data="filteredEnvRows" size="small" border stripe max-height="72vh" style="width:100%" v-loading="envLoading">
      <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
      <el-table-column prop="name" label="变量名" min-width="240"></el-table-column>
      <el-table-column label="值" min-width="320">
        <template #default="scope">
          <span v-if="scope.row.value !== ''">[[ scope.row.value ]]</span>
          <el-tag v-else size="small" type="info">[[ scope.row.source || 'valueFrom' ]]</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button type="primary" @click="envVisible = false">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 日志目录弹窗（SSH 直连 NFS：列出/查看/下载） -->
  <el-dialog v-model="lfVisible" :title="'日志目录 - ' + (lfServiceName || '')" width="70%" top="10vh">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
      <span style="color:#909399;font-size:12px;word-break:break-all;">[[ lfShortPath() ]]</span>
      <span style="color:#c0c4cc;font-size:12px;white-space:nowrap;">共 [[ lfFiles.length ]] 个文件（点击文件名可直接查看）</span>
      <el-button size="small" style="margin-left:auto;" @click="loadLogFiles">刷新</el-button>
    </div>
    <el-table :data="lfFiles" size="small" border stripe max-height="65vh" style="width:100%" v-loading="lfLoading">
      <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
      <el-table-column label="文件名" min-width="320">
        <template #default="scope">
          <span class="svc-logfile-name" :class="{ 'is-running': !!lfRunningPod(scope.row.name) }"
                :title="lfRunningPod(scope.row.name) ? ('运行中 Pod: ' + lfRunningPod(scope.row.name) + '，点击查看内容') : '点击查看内容'"
                @click="viewLogfile(scope.row)">[[ scope.row.name ]]</span>
        </template>
      </el-table-column>
      <el-table-column prop="size_str" label="大小" width="100" align="right"></el-table-column>
      <el-table-column prop="mtime_str" label="修改时间" width="170"></el-table-column>
      <el-table-column label="操作" width="140" align="center">
        <template #default="scope">
          <el-button link type="primary" size="small" @click="viewLogfile(scope.row)">查看</el-button>
          <el-button link type="primary" size="small" @click="downloadLogfile(scope.row)">下载</el-button>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button type="primary" @click="lfVisible = false">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 日志文件内容查看弹窗 -->
  <el-dialog v-model="lfContentVisible" :title="'日志内容 - ' + (lfContentFile || '')" width="80%" top="10vh"
             class="svc-logfile-dialog" :close-on-click-modal="false" append-to-body>
    <pre class="svc-logfile-pre" ref="lfContentBox" v-loading="lfContentLoading"
         element-loading-background="rgba(10, 46, 60, 0.9)">[[ lfContent ]]</pre>
  </el-dialog>

  <!-- 部署配置弹窗 -->
  <el-dialog v-model="yamlVisible" :title="'部署配置 - ' + (yamlFile || '')" width="900px">
    <div style="position:relative;">
      <button class="svc-copy-btn" @click="copyText(yamlContent, 'YAML')">复制</button>
      <pre class="svc-yaml-pre">[[ yamlContent ]]</pre>
    </div>
  </el-dialog>

  <!-- Nacos 配置内容查看/编辑弹窗：深色护眼 + 语法高亮 + Ctrl+F 搜索高亮 -->
  <el-dialog v-model="configEditorVisible" width="80%" top="10vh" class="svc-config-dialog"
             :close-on-click-modal="false" append-to-body @close="onConfigDialogClose">
    <template #header>
      <div class="svc-config-header">
        <span class="svc-config-title">Nacos 配置 - [[ configRow ? configRow.dataId : '' ]]</span>
        <span class="svc-config-count" v-if="!configNotFound">共 [[ cfgLineCount ]] 行</span>
        <span style="margin-left:auto;display:flex;gap:8px;align-items:center;">
          <el-input v-if="!configEditMode && !configNotFound" ref="configSearchInput" v-model="configSearch" size="small" clearable
                    placeholder="搜索（Ctrl+F）" style="width:220px;"></el-input>
          <span v-if="!configEditMode && !configNotFound && configSearch" class="svc-cfg-matches">
            [[ matchCount > 0 ? matchCount + ' 处匹配' : '无匹配' ]]
          </span>
          <el-button v-if="!configEditMode && !configNotFound && canUpdateNacos" size="small" @click="configEditMode = true">编辑</el-button>
          <el-button v-if="configEditMode" size="small" @click="cancelConfigEdit">取消编辑</el-button>
          <el-button v-if="configEditMode && canUpdateNacos" size="small" type="primary" :loading="publishing" @click="publishConfig">发布更新</el-button>
          <el-button size="small" @click="configEditorVisible = false">关闭</el-button>
        </span>
      </div>
    </template>
    <div v-loading="configLoading">
      <!-- 配置不存在：引导新增（dataId 自动生成 {服务名}.yaml） -->
      <div v-if="configNotFound && !configEditMode" class="svc-cfg-empty">
        <div style="font-size:14px;color:#909399;margin-bottom:8px">
          配置 <b style="color:#606266">[[ configRow ? configRow.dataId : '' ]]</b> 在当前 namespace 中不存在
        </div>
        <div style="font-size:12px;color:#c0c4cc;margin-bottom:18px">
          是否新增该配置？dataId 已按「服务名.yaml」自动生成，内容为 yaml 格式
        </div>
        <el-button v-if="canUpdateNacos" type="primary" size="small" @click="createNewConfig">新增配置</el-button>
      </div>
      <!-- 内容区：右上角复制按钮 + 查看/编辑层 -->
      <div class="svc-cfg-content">
        <div class="svc-cfg-code">
          <el-button v-if="!configNotFound" class="svc-cfg-copy-btn" size="small" @click="copyConfigContent">复制</el-button>
          <!-- 行号栏：与内容同步滚动 -->
          <div class="svc-cfg-gutter" ref="cfgGutter">
            <div v-for="n in cfgLineCount" :key="n" class="svc-cfg-gutter-line">[[ n ]]</div>
          </div>
          <pre v-show="!configEditMode && !configNotFound" class="svc-config-pre" ref="configPre"
               @scroll="syncCfgGutter('pre')"><code ref="configCode" class="language-yaml"></code></pre>
          <!-- 编辑模式：透明 textarea 叠在高亮层上，输入即实时语法高亮 -->
          <div v-show="configEditMode" class="svc-editor-wrap">
            <pre class="svc-config-pre svc-editor-pre" aria-hidden="true"><code ref="configCodeEdit" class="language-yaml"></code></pre>
            <textarea ref="configTextarea" :value="configContent" @input="configContent = $event.target.value"
                      @scroll="syncCfgGutter('edit')" class="svc-editor-textarea" spellcheck="false"></textarea>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>

  <!-- 发布对比弹框（参考 Nginx 配置保存对比） -->
  <el-dialog v-model="diffVisible" width="1200px" top="3vh" :close-on-click-modal="false" :close-on-press-escape="false"
             title="⚠️ 确认发布 Nacos 配置" append-to-body>
    <div style="margin-bottom:10px;padding:10px 14px;background:#fff7e6;border:1px solid #ffe58f;border-radius:4px;font-size:13px;color:#ad6800">
      <template v-if="configIsNew">此操作将在 Nacos 当前 namespace 中 <b>新增</b> 配置 <b>[[ configRow ? configRow.dataId : '' ]]</b>，发布后对该 namespace 下服务立即生效。请确认以下内容无误。</template>
      <template v-else>此操作将覆盖 Nacos 中 <b>[[ configRow ? configRow.dataId : '' ]]</b> 的配置内容，发布后对该 namespace 下服务立即生效。请确认以下修改无误。</template>
    </div>
    <div style="margin-bottom:8px;display:flex;gap:16px;font-size:12px;color:#909399">
      <span>新增 <span style="display:inline-block;width:12px;height:12px;background:#e6ffec;border:1px solid #b7f5c8;vertical-align:middle;margin:0 2px"></span></span>
      <span>删除 <span style="display:inline-block;width:12px;height:12px;background:#ffebe9;border:1px solid #f5b7b7;vertical-align:middle;margin:0 2px"></span></span>
      <span>修改 <span style="display:inline-block;width:12px;height:12px;background:#fff8e1;border:1px solid #f5e0b7;vertical-align:middle;margin:0 2px"></span></span>
      <div style="flex:1"></div>
      <span>[[ diffStats.added ]] 行新增，[[ diffStats.removed ]] 行删除，[[ diffStats.modified ]] 行修改</span>
    </div>
    <div class="diff-container" style="height:55vh;overflow:auto;border:1px solid #e8e8e8;border-radius:4px">
      <table class="diff-table">
        <colgroup>
          <col style="width:46px"><col><col style="width:46px"><col>
        </colgroup>
        <tbody>
          <tr v-for="(row, i) in diffRows" :key="i" :class="'diff-row ' + (row.type === 'fold' ? 'diff-fold' : 'diff-' + row.type)">
            <td v-if="row.type === 'fold'" colspan="4" class="diff-fold-cell">⋯ 省略 [[ row.count ]] 行相同内容 ⋯</td>
            <template v-else>
              <td class="diff-ln">[[ row.oldLn ]]</td>
              <td class="diff-cell diff-cell-old"><pre>[[ row.oldText ]]</pre></td>
              <td class="diff-ln">[[ row.newLn ]]</td>
              <td class="diff-cell diff-cell-new"><pre>[[ row.newText ]]</pre></td>
            </template>
          </tr>
        </tbody>
      </table>
    </div>
    <template #footer>
      <el-button @click="diffVisible = false">返回编辑</el-button>
      <el-button type="primary" :loading="publishing" @click="doPublish">确认发布</el-button>
    </template>
  </el-dialog>

  <!-- 选择服务目录弹窗（部署步骤 waiting 时勾选回填模板，需重新构建） -->
  <el-dialog v-model="selectDirsVisible" :title="'选择服务目录 - ' + (bpBuild?.build_no || '')" width="760px" :close-on-click-modal="false">
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom:10px">
      模板未配置服务目录，本次构建已跳过产物收集/打镜像/推送。请浏览该构建编译后的代码目录，勾选要构建的服务目录保存到模板，然后重新触发构建。
    </el-alert>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
      <span style="font-size:13px;white-space:nowrap">
        <el-link type="primary" :underline="false" @click="loadCodeDirs('')">code目录</el-link>
        <template v-for="(seg, i) in selectDirsSegments" :key="i">
          <span style="margin:0 3px;color:#c0c4cc">/</span>
          <el-link type="primary" :underline="false" @click="loadCodeDirs(selectDirsSegments.slice(0, i + 1).join('/'))">[[ seg ]]</el-link>
        </template>
      </span>
      <span style="flex:1"></span>
      <el-button size="small" :disabled="!selectDirsPath" @click="loadCodeDirs(selectDirsParent)">上级</el-button>
      <el-button size="small" @click="loadCodeDirs(selectDirsPath)">刷新</el-button>
      </div>
      <div style="font-size:12px;color:#909399;margin:4px 0 8px">产物目录：<b style="color:#303133">[[ selectDirsArtifactDir || '未设置（收集整服务目录）' ]]</b>（点目录行「设为产物」/文件行「设为该类产物」快速设置）</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:6px">
        <el-button link type="primary" size="small" @click="checkAllSelectDirs(true)">全选</el-button>
        <el-button link type="primary" size="small" @click="checkAllSelectDirs(false)">取消全选</el-button>
      </div>
    <el-table :data="selectDirsEntries" size="small" border stripe v-loading="selectDirsLoading" style="width:100%" max-height="40vh">
      <el-table-column label="名称" min-width="320">
        <template #default="s">
          <span v-if="s.row.type === 'dir'" style="display:inline-flex;align-items:center;gap:6px">
            <el-checkbox :model-value="!!selectDirsChecked[selectDirJoin(s.row.name)]"
                         @change="(v) => toggleSelectDir(selectDirJoin(s.row.name), v)" />
            <span style="cursor:pointer;color:#409eff" @click="loadCodeDirs(selectDirJoin(s.row.name))">📁 [[ s.row.name ]]</span>
            <el-link type="success" :underline="false" style="font-size:12px" @click="setDirAsArtifact(s.row.name)">设为产物</el-link>
          </span>
          <span v-else style="display:inline-flex;align-items:center;gap:6px">
            📄 [[ s.row.name ]]
            <el-link type="success" :underline="false" style="font-size:12px" @click="setFileAsArtifact(s.row.name)">设为该类产物</el-link>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="80" align="center">
        <template #default="s"><el-tag size="small" :type="s.row.type === 'dir' ? 'primary' : 'info'">[[ s.row.type ]]</el-tag></template>
      </el-table-column>
    </el-table>
    <div style="margin-top:10px">
      <div style="font-size:13px;color:#606266;margin-bottom:6px">已选服务目录（[[ selectDirsList.length ]]）：</div>
      <div v-if="!selectDirsList.length" style="color:#c0c4cc;font-size:12px">尚未选择，至少勾选一个目录</div>
      <el-tag v-for="(d, i) in selectDirsList" :key="d" size="small" closable style="margin:0 6px 6px 0" @close="removeSelectDir(i)">[[ d ]]</el-tag>
    </div>
    <template #footer>
      <el-button @click="selectDirsVisible = false">取消</el-button>
      <el-button type="primary" :loading="selectDirsSaving" :disabled="!selectDirsList.length" @click="confirmSelectDirs">保存配置</el-button>
    </template>
  </el-dialog>
  </div><!-- /serviceinfo-main -->
</div>
`,
  data() {
    return {
      projects: [],
      projectList: [],  // [{id, name}] 保留 id 供快捷部署触发
      selectedProject: '',
      envs: [],
      envList: [],  // [{id, environment}] 保留 id 供快捷部署触发
      selectedEnv: '',
      favorites: [],          // 当前用户的环境收藏（来自后端，按 user_id 隔离）
      favCollapsed: false,    // 收藏栏是否收起
      services: [],
      loading: false,
      k8sError: '',
      svcStream: null,       // 服务卡片 SSE 流（EventSource）
      svcStreamRetry: null,  // SSE 断连重连定时器
      envLoading: false,     // 环境变量弹窗加载中

      // 快捷部署弹窗（与环境信息页构建弹窗完全一致：分支/服务/类型 + 进度抽屉）
      buildDialogVisible: false,
      buildType: 'backend',
      buildEnv: null,
      buildBranch: '',
      branchOptions: [],
      branchFiltered: [],
      branchLoading: false,
      recentBranches: [],
      recentBranchesFiltered: [],
      serviceToggles: {},
      serviceOptions: [],
      servicesLoaded: false,
      buildTriggering: false,
      // 构建进度抽屉
      bpDrawerVisible: false,
      bpBuild: null,
      bpSteps: [],
      bpLogFull: '',  // 全量日志缓冲（仅 all 模式 SSE 累积）
      bpLogByStep: {},  // 步骤归属日志缓冲（后端帧带 step，前端纯渲染）
      bpLogMode: 'all',
      bpStepES: null,
      bpES: null,
      bpNow: Date.now(),
      bpTimer: null,
      selectedEnvData: {},  // 当前环境详情（含最近构建记录 builds）
      activeBuild: null,   // 当前环境进行中的构建（SSE 推送，点击打开进度抽屉）
      envBuildStream: null,
      branchTreeMode: false,  // 分支展示：false=平铺列表，true=按目录树形
      branchTreeFilter: '',
      branchSearch: '',   // 平铺分支输入框：选择/过滤（回车直接采用输入值）

      // 日志弹窗
      logVisible: false,
      logFullscreen: false,  // 日志全屏模式（覆盖整个窗口，ESC 退出）
      logServiceName: '',
      logPods: [],
      logPod: '',
      logTail: 500,
      logLines: [],
      logSearchWord: '', logSearchMatches: [], logSearchIdx: -1,
      logStream: null,
      streamConnected: false,
      logPaused: false,  // 暂停追踪：断开 SSE 但保留已加载日志，供手动翻找

      // 部署配置弹窗
      envVisible: false, envRows: [], envServiceName: '', envSearchWord: '',

      // 日志目录弹窗
      lfVisible: false, lfServiceName: '', lfPods: [], lfPath: '', lfFiles: [], lfLoading: false,
      lfContentVisible: false, lfContentFile: '', lfContent: '', lfContentLoading: false,
      yamlVisible: false,
      yamlFile: '',
      yamlContent: '',

      // Nacos 配置弹窗
      configEditorVisible: false,
      configRow: null,
      configContent: '',
      configLoading: false,
      configEditMode: false,
      configNotFound: false,
      configIsNew: false,
      configSearch: '',
      matchCount: 0,
      configOriginal: '',
      publishing: false,
      // 选择服务目录弹窗（部署等待时勾选回填模板）
      selectDirsVisible: false,
      selectDirsPath: '',
      selectDirsEntries: [],
      selectDirsLoading: false,
      selectDirsChecked: {},
      selectDirsList: [],
      selectDirsArtifactDir: '',   // 全局产物目录（各服务内统一子路径），随服务目录一并回填模板
      selectDirsFirstLoad: true,   // 仅首次加载目录时预填产物目录，避免浏览子目录时覆盖用户输入
      selectDirsSaving: false,
      // 发布对比
      diffVisible: false,
      diffRows: [],
      diffStats: { added: 0, removed: 0, modified: 0 },
    };
  },
  computed: {
    // 部署步骤 waiting：后端未配置服务目录，需勾选回填后重新构建
    bpDeployWaiting() {
      return (this.bpSteps || []).some(s => s.key === 'deploy' && (
        s.status === 'waiting' || s.action === 'configure_artifact_dirs'
      ));
    },
    selectDirsSegments() { return this.selectDirsPath ? this.selectDirsPath.split('/').filter(Boolean) : []; },
    selectDirsParent() {
      const segs = this.selectDirsSegments;
      return segs.length > 1 ? segs.slice(0, -1).join('/') : '';
    },
    cfgLineCount() { return (this.configContent || '').split(String.fromCharCode(10)).length; },
    filteredEnvRows() {
      if (!this.envSearchWord) return this.envRows;
      return this.envRows.filter(r => this.isSubseqMatch(this.envSearchWord, r.name));
    },

    canUpdateNacos() {
      return this.$auth.hasPermission('op:nacos_config_update');
    },
    canDeploy() {
      return this.$auth.hasPermission('op:cicd_build');
    },
    selectedServiceCount() {
      return this.serviceOptions.filter(s => this.serviceToggles[s]).length;
    },
    // 全部勾选状态：所有服务开关都开启时为 true（供「全部勾选」开关联动）
    allServicesChecked() {
      return this.serviceOptions.length > 0 && this.serviceOptions.every(s => this.serviceToggles[s]);
    },
    // 当前环境最近构建记录（backend/frontend 两行，按时间倒序）
    envBuilds() {
      const builds = (this.selectedEnvData || {}).builds || {};
      const rows = [];
      if (builds.backend) rows.push({ ...builds.backend, project_type: 'backend' });
      if (builds.frontend) rows.push({ ...builds.frontend, project_type: 'frontend' });
      return rows.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    },
    buildStatusText() {
      return (st) => ({ pending: '等待中', running: '构建中', success: '成功', failed: '失败', cancelled: '已取消' }[st] || st || '-');
    },
    // 最近一次构建（backend/frontend 取时间最新一条）——工具栏靠右展示执行人/分支/时间
    lastBuild() {
      return this.envBuilds[0] || null;
    },
    // 输入框关键字：仅手动输入时过滤（回填为 placeholder，不参与过滤）
    branchKw() {
      return (this.branchSearch || '').trim().toLowerCase();
    },
    // 点击输入框：清空默认分支提示（placeholder 自动消失），开始输入即过滤
    onBranchFocus() {
      this.branchSearch = '';
    },
    // 最近分支分组（最近构建选择过的分支，过滤后置顶；最多 5 个）
    branchRecentList() {
      const kw = this.branchKw;
      const list = kw
        ? this.recentBranches.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.recentBranches.slice();
      return list.slice(0, 5);
    },
    // 全部分支分组（过滤后，排除已在最近分支组内的，避免重复）
    branchAllList() {
      const kw = this.branchKw;
      const recent = this.recentBranches;
      const list = kw
        ? this.branchOptions.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.branchOptions.slice();
      return list.filter(b => !recent.includes(b));
    },
    // 分支目录树：按 / 分层构建（feature/release/hotfix 等目录可展开收起）
    branchTree() {
      const map = {};
      const tree = [];
      (this.branchOptions || []).forEach(b => {
        const parts = b.split('/');
        let level = tree;
        let path = '';
        parts.forEach((p, i) => {
          path = path ? path + '/' + p : p;
          if (i === parts.length - 1) {
            // 叶子 = 分支（完整路径）
            level.push({ key: 'branch-' + b, label: b, branch: b, isBranch: true });
            return;
          }
          let node = map[path];
          if (!node) {
            node = { key: 'dir-' + path, label: p, children: [] };
            map[path] = node;
            level.push(node);
          }
          level = node.children;
        });
      });
      return tree;
    },
  },
  watch: {
    branchTreeFilter(v) {
      this.$refs.branchTreeRef && this.$refs.branchTreeRef.filter(v);
    },
    configContent() {
      if (!this.configEditorVisible) return;
      if (this.configEditMode) this.renderEditView();
      else this.renderConfigView();
    },
    configSearch() {
      if (!this.configEditMode) this.renderConfigView();
    },
    configEditMode(v) {
      if (v) this.renderEditView();
      else this.renderConfigView();
    },
  },
  mounted() {
    this.loadFavorites();
    this.restoreLastSelection();
  },
  methods: {
    // ─── 环境收藏（按用户落库） ──────────────────────────────
    loadFavorites() {
      ajax('GET', '/api/deploy/service-info/favorites', null, (r) => {
        if (r.code === 200) this.favorites = r.data || [];
      });
    },
    // ─── 上次选择回填（localStorage 持久化，刷新后自动恢复） ──
    persistSelection() {
      if (!this.selectedProject || !this.selectedEnv) return;
      try {
        localStorage.setItem('svc_last_selection', JSON.stringify({
          project: this.selectedProject,
          env: this.selectedEnv,
        }));
      } catch (e) { /* 忽略存储异常 */ }
    },
    restoreLastSelection() {
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem('svc_last_selection') || 'null');
      } catch (e) { saved = null; }
      if (!saved || !saved.project) return;
      this.selectedProject = saved.project;
      // 环境列表需异步加载（与 onProjectChange 相同逻辑，但不能直接调它——它会清空 selectedEnv）
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(saved.project), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
        if (saved.env && this.envs.includes(saved.env)) {
          this.selectedEnv = saved.env;
          this.loadServices();
        } else if (saved.env) {
          // 环境已被删除：保留项目，仅提示重新选择环境
          ElementPlus.ElMessage.warning('上次选择的环境已不存在，请重新选择');
        }
      });
    },
    addFavorite() {
      if (!this.selectedProject || !this.selectedEnv) {
        ElementPlus.ElMessage.warning('请先选择项目与环境');
        return;
      }
      const proj = this.projectList.find(p => p.name === this.selectedProject);
      const env = this.envList.find(e => e.environment === this.selectedEnv) || this.selectedEnvData;
      if (!proj || !env || !env.id) {
        ElementPlus.ElMessage.warning('无法识别当前项目/环境');
        return;
      }
      if (this.favorites.some(f => f.project_name === this.selectedProject && f.env_name === this.selectedEnv)) {
        ElementPlus.ElMessage.info('已收藏');
        return;
      }
      ajax('POST', '/api/deploy/service-info/favorites', { project_id: proj.id, env_id: env.id }, (r) => {
        if (r.code === 200) {
          if (!this.favorites.some(f => f.id === r.data.id)) this.favorites.unshift(r.data);
          ElementPlus.ElMessage.success('已收藏');
        } else {
          ElementPlus.ElMessage.warning(r.msg || '收藏失败');
        }
      });
    },
    removeFavorite(id) {
      ajax('DELETE', '/api/deploy/service-info/favorites/' + id, null, (r) => {
        if (r.code === 200) {
          this.favorites = this.favorites.filter(f => f.id !== id);
        } else {
          ElementPlus.ElMessage.warning(r.msg || '取消收藏失败');
        }
      });
    },
    selectFavorite(item) {
      // 跨项目：重置并加载目标项目环境列表后回填；同项目：仅换环境
      if (this.selectedProject !== item.project_name) {
        this.closeEnvBuildStream();
        this.closeSvcStream();
        this.activeBuild = null;
        this.selectedEnv = '';
        this.services = [];
        this.envs = [];
        this.selectedProject = item.project_name;
      }
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(item.project_name), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
        if (this.envs.includes(item.env_name)) {
          this.selectedEnv = item.env_name;
          this.loadServices();
        } else {
          ElementPlus.ElMessage.warning('该环境已不存在，请重新选择');
        }
      });
    },
    toggleFavBar() {
      this.favCollapsed = !this.favCollapsed;
    },
    loadProjects() {
      ajax('GET', '/api/admin/projects', null, (r) => {
        this.projectList = r.data || [];
        this.projects = this.projectList.map(p => p.name);
      });
    },
    onProjectChange() {
      // 切换项目：立即断开上一个环境的构建状态 SSE 与服务卡片 SSE，再重置选择
      this.closeEnvBuildStream();
      this.closeSvcStream();
      this.activeBuild = null;
      this.selectedEnv = '';
      this.services = [];
      this.envs = [];
      if (!this.selectedProject) return;
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(this.selectedProject), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
      });
    },
    // ═══════════ 快捷部署（与环境信息页构建弹窗完全一致） ═══════════
    _buildPrefKey(envId) { return 'cicd_build_pref_' + envId; },
    _buildPrefLoad(envId) {
      try {
        const raw = localStorage.getItem(this._buildPrefKey(envId));
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    },
    _buildPrefSave() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      const enabled = this.serviceOptions.filter(s => this.serviceToggles[s]);
      try {
        localStorage.setItem(this._buildPrefKey(this.buildEnv.id), JSON.stringify({
          branch: this.buildBranch,
          services: enabled
        }));
      } catch (e) { /* 忽略存储异常 */ }
    },
    openDeploy() {
      // 实时从环境列表取当前选中环境（避免 selectedEnvData 未同步导致误报）
      const env = this.envList.find(e => e.environment === this.selectedEnv) || this.selectedEnvData;
      if (!env || !env.id) { ElementPlus.ElMessage.warning('请先选择环境'); return; }
      this.buildType = 'backend';
      this.openBuildDialog(env, 'backend');
    },
    onDeployTypeChange() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      this.openBuildDialog(this.buildEnv, this.buildType);
    },
    // 点击构建：立即弹窗（分支 git ls-remote 可能 1s+，异步加载不阻塞弹窗）
    openBuildDialog(row, type) {
      this.buildType = (type === 'frontend') ? 'frontend' : 'backend';
      this.buildEnv = row;
      if (!row.project_id) { ElementPlus.ElMessage.warning('缺少项目信息'); return; }

      this._initBuildDialog(row);
      this.buildDialogVisible = true;
      if (this.buildType === 'backend') this._loadBuildServices(row);
      // 分支异步加载：git ls-remote 到远程 Git（网络往返，约 1s），期间弹窗已可操作
      this.branchLoading = true;
      ajax('GET', '/api/cicd/builds/branches?project_id=' + row.project_id + '&project_type=' + this.buildType, null, (r) => {
        this.branchLoading = false;
        if (r.code === 200) {
          let branches = r.data || [];
          const lastBranch = (row.builds && row.builds[this.buildType] && row.builds[this.buildType].branch) || '';
          if (lastBranch && !branches.includes(lastBranch)) branches.unshift(lastBranch);
          this.branchOptions = branches;
          this.branchFiltered = branches;
        } else if (r.code === 400) {
          // 模板未配置 Git 地址：提示并收起弹窗（避免空分支弹窗）
          this.buildDialogVisible = false;
          ElementPlus.ElMessage.error(r.msg || r.message || '该项目未配置模板');
        } else {
          // 网络/服务异常（如 git 拉取失败）：保留弹窗，分支可手动输入
          ElementPlus.ElMessage.error((r.msg || r.message || '获取分支失败') + '，可手动输入分支');
        }
      }, () => { this.branchLoading = false; });
    },
    // 初始化构建弹窗状态（恢复上次偏好 + 最近使用分支）
    _initBuildDialog(row) {
      const pref = this._buildPrefLoad(row.id);
      const lastBranch = (row.builds && row.builds[this.buildType] && row.builds[this.buildType].branch) || '';
      // 回填最后一次执行的分支（最近构建分支优先，其次上次选择，兜底 master）；
      // 输入框以浅色 placeholder 提示该分支，不写入值（不过滤列表，不动直接应用）
      this.buildBranch = lastBranch || (pref && pref.branch) || 'master';
      this.branchSearch = '';
      this.recentBranches = [];
      this.recentBranchesFiltered = [];
      this.serviceToggles = {};
      this.serviceOptions = [];
      this.servicesLoaded = false;
      if (row.id) {
        ajax('GET', '/api/cicd/builds?environment_id=' + row.id, null, (r) => {
          if (r.code === 200) {
            const seen = new Set();
            const recent = [];
            (r.data || []).forEach(b => {
              if (b.branch && !seen.has(b.branch)) { seen.add(b.branch); recent.push(b.branch); }
            });
            this.recentBranches = recent.slice(0, 5);
            this.recentBranchesFiltered = this.recentBranches;
          }
        });
      }
    },
    // 加载服务列表（默认全部开启；上次为部分构建时恢复勾选）
    _loadBuildServices(row) {
      const pref = this._buildPrefLoad(row.id);
      ajax('GET', '/api/cicd/builds/services?project_id=' + row.project_id, null, (r) => {
        this.servicesLoaded = true;
        if (r.code === 200) {
          this.serviceOptions = r.data || [];
          const toggles = {};
          if (pref && Array.isArray(pref.services) && pref.services.length) {
            this.serviceOptions.forEach(s => { toggles[s] = pref.services.includes(s); });
            if (!this.serviceOptions.some(s => toggles[s])) {
              this.serviceOptions.forEach(s => { toggles[s] = true; });
            }
          } else {
            this.serviceOptions.forEach(s => { toggles[s] = true; });
          }
          this.serviceToggles = toggles;
        }
      }, () => { this.servicesLoaded = true; });
    },
    subsequenceMatch(text, keyword) {
      let i = 0;
      for (let j = 0; j < text.length && i < keyword.length; j++) {
        if (text[j] === keyword[i]) i++;
      }
      return i >= keyword.length;
    },
    filterBranches(query) {
      const kw = (query || '').trim().toLowerCase();
      if (!kw) {
        this.branchFiltered = this.branchOptions;
        this.recentBranchesFiltered = this.recentBranches;
        return;
      }
      this.branchFiltered = this.branchOptions.filter(b => this.subsequenceMatch(b.toLowerCase(), kw));
      this.recentBranchesFiltered = this.recentBranches.filter(b => this.subsequenceMatch(b.toLowerCase(), kw));
    },
    onBranchDrop(visible) {
      if (visible) {
        this.branchFiltered = this.branchOptions;
        this.recentBranchesFiltered = this.recentBranches;
        // 打开下拉从顶部开始，不定位到当前选中分支
        this.$nextTick(() => {
          document.querySelectorAll('.el-select-dropdown__wrap').forEach(w => { w.scrollTop = 0; });
        });
      }
    },
    toggleAllServices(val) {
      this.serviceOptions.forEach(s => { this.serviceToggles[s] = !!val; });
    },
    // 输入框回车：直接采用输入值作为分支（用于自定义/快速选择）
    applyBranchInput() {
      const v = (this.branchSearch || '').trim();
      if (v) this.buildBranch = v;
    },
    // 该分支是否为最近构建选择过的分支（置顶 + 标记）
    isRecentBranch(b) {
      return this.recentBranches.includes(b);
    },
    // 树形选择分支：叶子设置 buildBranch；目录节点由 el-tree 自动展开/收起
    onBranchNodeClick(data) {
      if (data && data.isBranch) {
        this.buildBranch = data.branch;
      }
    },
    filterBranchTree(value, data) {
      if (!value) return true;
      if (data.isBranch) return data.branch.toLowerCase().includes(value.toLowerCase());
      return (data.children || []).some(c => this.filterBranchTree(value, c));
    },
    executeBuild() {
      if (!this.buildBranch.trim()) { ElementPlus.ElMessage.warning('请选择或输入分支'); return; }
      let services = [];
      if (this.serviceOptions.length > 1) {
        services = this.serviceOptions.filter(s => this.serviceToggles[s]);
        if (!services.length) { ElementPlus.ElMessage.warning('请至少开启一个要构建的服务'); return; }
      }
      this.buildTriggering = true;
      const env = this.buildEnv;
      this._buildPrefSave();
      ajax('POST', '/api/cicd/builds/trigger', {
        project_id: env.project_id,
        environment_id: env.id,
        branch: this.buildBranch.trim(),
        services: services,
        project_type: this.buildType
      }, (res) => {
        this.buildTriggering = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success('构建已触发');
          this.buildDialogVisible = false;
          this.loadEnvs();
          this.loadServices();
        } else {
          ElementPlus.ElMessage.error(res.msg || '触发失败');
        }
      }, () => { this.buildTriggering = false; });
    },
    // ═══════════ 构建进度抽屉（与环境信息页一致） ═══════════
    openProgressDrawer(build) {
      this.bpBuild = build;
      this.bpSteps = [];
      this.bpLogFull = '';
      this.bpLogByStep = {};
      this.bpLogMode = 'all';
      this.bpDrawerVisible = true;
      this.stopBpTimer();
      this.bpNow = Date.now();
      this.bpTimer = setInterval(() => { this.bpNow = Date.now(); }, 100);
      this.connectBuildSteps();
    },
    connectBuildSteps() {
      this.disconnectBpSteps();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/steps/stream?token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpStepES = es;
      es.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        this.bpSteps = data.steps || [];
        if (!this.bpES) {
          this.connectBuildLog('all');
        }
        const buildStatus = data.build_status;
        if (buildStatus) {
          const prevStatus = this.bpBuild.status;
          this.bpBuild = Object.assign({}, this.bpBuild, { status: buildStatus });
          // 构建终态但部署步骤可能仍在执行（Master 自动部署），不能立即断开；
          // 等后端发 done 帧（构建终态 + 部署步骤终态）再断开步骤流
          if (data.done) {
            this.disconnectBpSteps();
          }
          if (['success', 'failed', 'cancelled'].includes(buildStatus)) {
            if (prevStatus === 'running' || prevStatus === 'pending') {
              this.loadEnvs();
            }
          }
        }
      };
      es.onerror = () => {
        es.close();
        this.bpStepES = null;
        this.fetchBuildSteps();
      };
    },
    disconnectBpSteps() {
      if (this.bpStepES) { this.bpStepES.close(); this.bpStepES = null; }
    },
    fetchBuildSteps() {
      if (!this.bpBuild) return;
      ajax('GET', '/api/cicd/builds/' + this.bpBuild.id + '/steps', null, (res) => {
        if (res.code === 200 && res.data) {
          this.bpSteps = res.data.steps || [];
          if (res.data.build_status) {
            this.bpBuild = Object.assign({}, this.bpBuild, { status: res.data.build_status });
          }
        }
      });
    },
    connectBuildLog(type) {
      // 始终只维持 1 条 all 模式 SSE；切换步骤只改本地视图，不重连
      this.disconnectBpLog();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/log?type=all&follow=true&token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpES = es;
      es.onmessage = (evt) => {
        let obj;
        try { obj = JSON.parse(evt.data); } catch (e) { return; }
        const text = obj.text || '';
        if (!text) return;
        this.bpLogFull += text;
        if (obj.step) {
          this.bpLogByStep[obj.step] = (this.bpLogByStep[obj.step] || '') + text;
        }
        this.$nextTick(() => {
          const c = this.$refs.bpLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = () => { es.close(); this.bpES = null; };
    },
    disconnectBpLog() {
      if (this.bpES) { this.bpES.close(); this.bpES = null; }
    },
    bpStepType(stepNo) {
      return { 1: 'git', 2: 'mvn', 3: 'product', 4: 'build', 5: 'push', 6: 'deploy' }[stepNo] || 'git';
    },
    bpStatusType(status) {
      const map = { success: 'success', failed: 'danger', running: 'warning', pending: 'info', cancelled: 'info' };
      return (typeof status === 'string' && map[status]) || 'info';
    },
    bpStatusText(status) {
      const map = { success: '成功', failed: '失败', running: '运行中', pending: '等待中', cancelled: '已取消' };
      if (typeof status === 'string' && map[status]) return map[status];
      return (typeof status === 'string' && status) || '';
    },
    bpStepStatus(step) {
      if (!step) return 'wait';
      if (step.status === 'success') return 'success';
      if (step.status === 'running' || step.status === 'waiting') return 'process';
      if (step.status === 'failed') return 'error';
      return 'wait';
    },
    // ─── 选择服务目录（部署等待时勾选回填模板）─────────────────────────
    openSelectDirsDialog() {
      this.selectDirsChecked = {};
      this.selectDirsList = [];
      this.selectDirsArtifactDir = '';
      this.selectDirsFirstLoad = true;
      this.selectDirsVisible = true;
      this.loadCodeDirs('');
    },
    loadCodeDirs(path) {
      if (!this.bpBuild) return;
      this.selectDirsPath = path || '';
      this.selectDirsLoading = true;
      const params = new URLSearchParams({ path: this.selectDirsPath });
      ajax('GET', '/api/cicd/builds/' + this.bpBuild.id + '/code-dirs?' + params.toString(), null, (r) => {
        this.selectDirsLoading = false;
        if (r.code === 200 && r.data) {
          this.selectDirsEntries = r.data.entries || [];
          if (this.selectDirsFirstLoad) {
            this.selectDirsArtifactDir = r.data.artifact_dir || '';
            this.selectDirsFirstLoad = false;
          }
        } else {
          this.selectDirsEntries = [];
          ElementPlus.ElMessage.error(r.msg || '读取目录失败');
        }
      }, () => { this.selectDirsLoading = false; });
    },
    selectDirJoin(name) {
      return this.selectDirsPath ? this.selectDirsPath + '/' + name : name;
    },
    // 计算 fullPath 相对于「已勾选服务目录」的子路径；无匹配时用首段（服务目录）兜底
    relFromService(fullPath) {
      let rel = fullPath, best = '';
      for (const svc of this.selectDirsList) {
        if (fullPath === svc) { best = svc; rel = ''; break; }
        if (fullPath.startsWith(svc + '/') && svc.length > best.length) { best = svc; rel = fullPath.slice(svc.length + 1); }
      }
      if (!best) {
        const segs = fullPath.split('/');
        rel = segs.length > 1 ? segs.slice(1).join('/') : '';
      }
      return rel;
    },
    // 目录行：设定该目录为产物目录（相对服务目录的子路径）
    setDirAsArtifact(name) {
      const rel = this.relFromService(this.selectDirJoin(name));
      this.selectDirsArtifactDir = rel;
      ElementPlus.ElMessage.success(rel ? ('已设定产物目录：' + rel) : '已设定：收集服务根目录全部内容');
    },
    // 文件行：设定此类文件为产物，按扩展名填入通配符（*.ext 或 *）
    setFileAsArtifact(name) {
      const dirRel = this.relFromService(this.selectDirsPath);
      const dot = name.lastIndexOf('.');
      const wc = dot > 0 ? '*' + name.slice(dot) : '*';
      const val = dirRel ? dirRel + '/' + wc : wc;
      ElementPlus.ElMessageBox.confirm('设定此类文件（' + wc + '）为产物？将填入：' + val, '设定产物', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'info'
      }).then(() => {
        this.selectDirsArtifactDir = val;
        ElementPlus.ElMessage.success('已设定产物：' + val);
      }).catch(() => {});
    },
    // 全选/取消全选：全选作用于当前视图 dir 行（打开弹窗默认顶层=全部服务）；取消全选清空所有勾选
    checkAllSelectDirs(val) {
      if (!val) {
        this.selectDirsChecked = {};
        this.selectDirsList = [];
        return;
      }
      this.selectDirsEntries.filter(e => e.type === 'dir').forEach(e => {
        this.toggleSelectDir(this.selectDirJoin(e.name), true);
      });
    },
    toggleSelectDir(name, v) {
      if (v) {
        this.selectDirsChecked[name] = true;
        if (!this.selectDirsList.includes(name)) this.selectDirsList.push(name);
      } else {
        delete this.selectDirsChecked[name];
        const i = this.selectDirsList.indexOf(name);
        if (i > -1) this.selectDirsList.splice(i, 1);
      }
    },
    removeSelectDir(i) {
      const name = this.selectDirsList[i];
      this.selectDirsList.splice(i, 1);
      if (name) delete this.selectDirsChecked[name];
    },
    confirmSelectDirs() {
      if (!this.selectDirsList.length) { ElementPlus.ElMessage.warning('请至少勾选一个服务目录'); return; }
      this.selectDirsSaving = true;
      ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/configure-dirs',
        { artifact_dirs: this.selectDirsList.slice(), artifact_dir: (this.selectDirsArtifactDir || '').trim() }, (res) => {
        this.selectDirsSaving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '服务目录已回填到流程模板，请重新触发构建');
          this.selectDirsVisible = false;
          this.loadEnvs();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      }, () => { this.selectDirsSaving = false; });
    },
    parseStepTime(str) {
      const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?/.exec(str || '');
      if (!m) return NaN;
      const ms = m[7] ? m[7].padEnd(3, '0') : '0';
      return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], +ms).getTime();
    },
    fmtDuration(sec) {
      sec = Math.max(0, sec);
      const s = Math.floor(sec);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const ss = (s % 60).toString().padStart(2, '0');
      const dec = Math.round((sec - s) * 10);
      if (h > 0) return h + ':' + m.toString().padStart(2, '0') + ':' + ss;
      if (m > 0) return m + ':' + ss;
      return s + '.' + dec + 's';
    },
    bpStepDuration(s) {
      if (s.status === 'running' && s.started_at) {
        const st = this.parseStepTime(s.started_at);
        if (!isNaN(st)) return this.fmtDuration((this.bpNow - st) / 1000);
      }
      if (s.duration) return this.fmtDuration(s.duration);
      return '';
    },
    // 当前视图日志（后端已按步骤归属拆分，前端仅取缓冲 + 渲染限量 500KB）
    bpLogView() {
      let text = this.bpLogMode === 'all' ? this.bpLogFull : (this.bpLogByStep[this.bpLogMode] || '');
      if (!text) return '';
      const MAX = 512000;  // 500KB
      if (text.length > MAX) {
        return '...（日志过长，仅显示尾部 ' + Math.round(MAX / 1024) + 'KB）...\n' + text.slice(-MAX);
      }
      return text;
    },
    switchBpLog(stepNo) {
      // 切换步骤只改本地视图，不重连 SSE
      this.bpLogMode = this.bpStepType(stepNo);
    },
    switchBpLogAll() {
      this.bpLogMode = 'all';
    },
    stopBpPolling() {
      this.disconnectBpSteps();
      this.disconnectBpLog();
    },
    stopBpTimer() {
      if (this.bpTimer) { clearInterval(this.bpTimer); this.bpTimer = null; }
    },
    closeProgressDrawer() {
      this.bpDrawerVisible = false;
      this.stopBpPolling();
      this.stopBpTimer();
    },
    cancelBuild() {
      if (!this.bpBuild) return;
      ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/cancel', null, (res) => {
        if (res.code === 200) ElementPlus.ElMessage.success('已请求取消');
        else ElementPlus.ElMessage.error(res.msg || '取消失败');
      });
    },
    rerunFromStep(stepNo) {
      if (!this.bpBuild) return;
      const step = this.bpSteps.find(s => s.step_no === stepNo);
      const stepName = step ? step.name : ('步骤' + stepNo);
      ElementPlus.ElMessageBox.confirm(
        '将从「' + stepName + '」开始重新执行至最后一步，复用已完成步骤的代码与产物（不重新克隆）。确定继续？',
        '从指定步骤重跑',
        { confirmButtonText: '确定重跑', cancelButtonText: '取消', type: 'warning' }
      ).then(() => {
        ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/rerun', { start_step: stepNo }, (res) => {
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg || '已加入重跑队列');
            this.bpBuild = Object.assign({}, this.bpBuild, res.data || {}, { error_msg: '' });
            this.bpLogFull = '';
            this.connectBuildSteps();
            this.connectBuildLog('all');
          } else {
            ElementPlus.ElMessage.error(res.msg || '重跑失败');
          }
        });
      }).catch(() => { /* 取消确认 */ });
    },
    // 拉取环境列表并记录当前环境的构建记录（builds：backend/frontend 最近构建）
    loadEnvs() {
      if (!this.selectedProject) return;
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(this.selectedProject), null, (r) => {
        if (r.code === 200) {
          this.envList = ((r.data || {}).list || []);
          this.envs = this.envList.map(e => e.environment);
          this.syncSelectedEnvData();
        }
      });
    },
    syncSelectedEnvData() {
      const cur = this.envList.find(e => e.environment === this.selectedEnv);
      this.selectedEnvData = cur || {};
      this.subscribeEnvBuilds();
    },
    // 订阅环境进行中构建状态（SSE，5s 一帧；构建可能来自环境信息页）。
    // 每次订阅前先断开上一个 SSE；切换环境/项目后，旧连接残留帧按 environment_id 丢弃，
    // 避免误把上个环境的构建状态显示在当前环境上。
    subscribeEnvBuilds() {
      this.closeEnvBuildStream();
      this.activeBuild = null;
      const env = this.selectedEnvData;
      if (!env || !env.id) return;
      const envId = env.id;
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/cicd/builds/env/' + envId + '/stream?token=' + encodeURIComponent(token));
      this.envBuildStream = es;
      es.onmessage = (evt) => {
        try {
          const d = JSON.parse(evt.data);
          // 流已断开或环境已切换：丢弃不属于当前环境的推送
          if (d.environment_id !== envId || !this.envBuildStream || this.selectedEnvData.id !== envId) return;
          const builds = d.builds || [];
          const run = builds.find(b => b.status === 'running') || builds.find(b => b.status === 'pending') || null;
          const wasRunning = !!this.activeBuild;
          this.activeBuild = run ? { id: run.id, build_no: run.build_no, status: run.status, project_type: run.project_type, branch: run.branch, current_step: run.current_step || '' } : null;
          // 进行中构建结束：刷新普通 list 接口，让「最近构建」状态及时更新
          if (wasRunning && !run) this.loadEnvs();
        } catch (e) { /* 忽略解析错误 */ }
      };
      es.onerror = () => {
        es.close();
        this.envBuildStream = null;
        // 流断开时清掉残留的「构建中」指示，避免 SSE 断开后 UI 卡死在构建态
        if (this.activeBuild) {
          this.activeBuild = null;
          this.loadEnvs();
        }
        // 自动重连：10s 后重建 SSE（仅当环境未切换、未主动关闭）
        setTimeout(() => {
          if (this.selectedEnvData && this.selectedEnvData.id === envId && !this.envBuildStream) {
            this.subscribeEnvBuilds();
          }
        }, 10000);
      };
    },
    closeEnvBuildStream() {
      if (this.envBuildStream) { this.envBuildStream.close(); this.envBuildStream = null; }
    },
    loadServices() {
      // 主数据源：SSE 实时流（快照 + 增量，滚动更新实时可见）；断连/出错自动回退 HTTP
      if (!this.selectedProject || !this.selectedEnv) return;
      this.persistSelection();  // 记录"上次选择"，供页面刷新后回填
      this.syncSelectedEnvData();
      this.closeSvcStream();
      this.k8sError = '';
      this.loading = true;
      this.connectSvcStream();
    },
    // 服务卡片 SSE 订阅：snapshot/update 全量替换 services；error/多次断连回退 HTTP
    connectSvcStream() {
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject,
        env: this.selectedEnv,
        token: token,
      });
      const es = new EventSource('/api/deploy/service-info/stream?' + params.toString());
      this.svcStream = es;
      let failCount = 0;
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.type === 'snapshot' || d.type === 'update') {
            this.services = d.services || [];
            this.k8sError = '';
            this.loading = false;
          } else if (d.type === 'error') {
            this.k8sError = d.error || 'SSE 不可用';
            this.closeSvcStream();
            this.loadServicesHttp();
          }
          // heartbeat 忽略（保活）
        } catch (err) { /* 忽略非法帧 */ }
      };
      es.onerror = () => {
        // 网络断连：EventSource 默认自动重连；连续失败则回退 HTTP
        failCount++;
        if (failCount >= 3) {
          this.closeSvcStream();
          this.loading = false;
          this.k8sError = 'SSE 连接失败，已回退 HTTP';
          this.loadServicesHttp();
        }
      };
    },
    closeSvcStream() {
      if (this.svcStream) {
        this.svcStream.close();
        this.svcStream = null;
      }
    },
    // HTTP 列表回退（SSE 不可用 / 后端 K8s 不可用）
    loadServicesHttp() {
      const url = '/api/deploy/service-info/list?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv);
      ajax('GET', url, null, (r) => {
        const d = r.data || {};
        this.services = d.list || [];
        if (d.k8s_error) this.k8sError = d.k8s_error;
        this.loading = false;
      });
    },
    // 镜像标题：多镜像（滚动更新期间）时展示全部
    svcImageTitle(svc) {
      const imgs = (svc.images && svc.images.length) ? svc.images : (svc.image ? [svc.image] : []);
      return imgs.join('\n');
    },

    podTagType(pod) {
      if (pod.reason) return 'danger';
      if (pod.phase === 'Running') return 'success';
      if (pod.phase === 'Pending') return 'warning';
      return 'info';
    },
    // 状态标签文案：phase 中文 + 异常原因
    podStatusText(pod) {
      const map = { Running: '运行中', Pending: '等待中', Succeeded: '已完成', Failed: '失败', Unknown: '未知' };
      const base = map[pod.phase] || pod.phase || 'Unknown';
      return pod.reason ? base + '·' + pod.reason : base;
    },
    svcCardDotClass(svc) {
      if (!svc.pods || !svc.pods.length) return 'off';
      if (svc.pods.some(p => p.reason)) return 'err';
      if (svc.pods.some(p => p.phase !== 'Running')) return 'warn';
      return 'ok';
    },
    svcCardDotTitle(svc) {
      if (!svc.pods || !svc.pods.length) return '未部署（无 Pod）';
      const running = svc.pods.filter(p => p.phase === 'Running' && !p.reason).length;
      return running + '/' + svc.pods.length + ' 个 Pod 运行中';
    },

    // ─── 运行日志（SSE） ─────────────────────────────────

    openLog(row, pod) {
      this.logServiceName = row.name;
      this.logPods = row.pods || [];
      this.logPod = pod ? pod.name : (this.logPods[0] ? this.logPods[0].name : '');
      this.logLines = [];
      this.logVisible = true;
      if (this.logPod) this.connectLogStream();
    },
    // ─── 日志搜索（Ctrl+F） ────────────────────────────────
    highlightLogLine(line) {
      let html = this._escapeHtml(String(line == null ? '' : line));
      // 行首时间戳着色（仅行首，其他地方的时间不特殊显示）：2026-08-12 13:57:47.101 或 13:57:47.101
      html = html.replace(/^(\s*)((\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)/,
        '$1<span class="svc-log-time">$2</span>');
      // Java 方法/行数着色：[类.方法,行号] 或 [lambda$x,行号]
      html = html.replace(/\[([^\],\[\s]+),(\d+)\]/g,
        '[<span class="svc-log-method">$1</span>,<span class="svc-log-line">$2</span>]');
      // 搜索高亮（split/join 方式，避免转义问题）
      if (this.logSearchWord) {
        const q = this._escapeHtml(this.logSearchWord);
        if (q) html = html.split(q).join('<mark style="background:#e6a23c;color:#1e1e1e;border-radius:2px">' + q + '</mark>');
      }
      return html;
    },
    isLogMatch(i) {
      if (!this.logSearchWord) return false;
      const q = this.logSearchWord.toLowerCase();
      return String(this.logLines[i]).toLowerCase().includes(q);
    },
    _escapeHtml(text) {
      return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
    updateLogSearch() {
      this.logSearchMatches = [];
      if (!this.logSearchWord) { this.logSearchIdx = -1; return; }
      const q = this.logSearchWord.toLowerCase();
      this.logLines.forEach((line, i) => { if (String(line).toLowerCase().includes(q)) this.logSearchMatches.push(i); });
      this.logSearchIdx = this.logSearchMatches.length ? 0 : -1;
      this._scrollToMatch();
    },
    logSearchJump(dir) {
      if (!this.logSearchMatches.length) return;
      this.logSearchIdx = (this.logSearchIdx + dir + this.logSearchMatches.length) % this.logSearchMatches.length;
      this._scrollToMatch();
    },
    _scrollToMatch() {
      const idx = this.logSearchIdx;
      if (idx < 0 || !this.logSearchMatches.length) return;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (!box) return;
        const el = document.getElementById('logline-' + this.logSearchMatches[idx]);
        if (el) box.scrollTop = el.offsetTop - box.offsetTop - 8;
      });
    },
    onLogKeydown(e) {
      if (!this.logVisible) return;
      if (e.key === 'Escape') {
        // 弹窗内展开的下拉/弹层（如日志行数选择）的 ESC 先交由组件自身关闭，避免误退出全屏
        const t = e.target;
        if (t && t.closest && t.closest('.el-select, .el-select-dropdown, .el-popper')) return;
        // 全屏时 ESC 仅退出全屏（弹窗自身 ESC 关闭在全屏态已禁用）；非全屏由 el-dialog 原生关闭
        if (this.logFullscreen) {
          this.logFullscreen = false;
          e.preventDefault();
        }
        return;
      }
      if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        if (this.$refs.logSearch) this.$refs.logSearch.focus();
      }
    },
    // 日志全屏切换（同一终端 DOM，流不断开，切换后滚动到底部）
    toggleLogFullscreen() {
      this.logFullscreen = !this.logFullscreen;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = box.scrollHeight;
      });
    },
    // 弹窗关闭（含 ESC 非全屏关闭）：重置全屏态并断开日志流
    onLogDialogClose() {
      this.logFullscreen = false;
      this.closeLogStream();
    },

    connectLogStream() {
      this.closeLogStream();
      this.logPaused = false;  // 重连即恢复实时追踪
      if (!this.logPod) return;
      this.logLines = [];
      this.streamConnected = false;
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject,
        env: this.selectedEnv,
        pod: this.logPod,
        service: this.logServiceName || '',
        tail: String(this.logTail),
        token: token,
      });
      const es = new EventSource('/api/deploy/service-info/log/stream?' + params.toString());
      this.logStream = es;
      es.onopen = () => { this.streamConnected = true; };
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.error) {
            this.logLines.push('[错误] ' + d.error);
            this.closeLogStream();
            return;
          }
          if (d.end) {
            this.logLines.push('── 日志流结束（Pod 退出或重启）──');
            this.closeLogStream();
            return;
          }
          this.logLines.push(d.line);
          // 防内存膨胀：仅保留最近 2000 行
          if (this.logLines.length > 2000) this.logLines.splice(0, this.logLines.length - 2000);
          Vue.nextTick(() => {
            const box = this.$refs.logBox;
            if (box) box.scrollTop = box.scrollHeight;
          });
        } catch (err) { /* 忽略非法帧 */ }
      };
      es.onerror = () => {
        // 日志流断连不自动重连（避免历史行重复刷屏），置为未连接由用户手动重连
        this.streamConnected = false;
        es.close();
        this.logStream = null;
      };
    },
    // 暂停/恢复追踪：暂停直接断开 SSE（不积压日志，保留已加载内容供手动翻找）；恢复则重新加载日志并继续 follow
    toggleLogPause() {
      if (this.logPaused) {
        this.connectLogStream();
      } else {
        this.closeLogStream();
        this.logPaused = true;
      }
    },
    closeLogStream() {
      if (this.logStream) {
        this.logStream.close();
        this.logStream = null;
      }
      this.streamConnected = false;
    },
    // 清屏：仅清空前端缓冲日志，不影响后端/SSE 流（新日志继续追加）
    clearLogScreen() {
      this.logLines = [];
      this.logSearchWord = '';
      this.logSearchMatches = [];
      this.logSearchIdx = -1;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = 0;
      });
    },

    // ─── 部署配置 ─────────────────────────────────────────

    // 子序列匹配（忽略大小写与非字母数字符号）：只匹配变量名
    isSubseqMatch(query, name) {
      const q = String(query || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      const n = String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      if (!q) return true;
      let qi = 0;
      for (let i = 0; i < n.length && qi < q.length; i++) {
        if (n[i] === q[qi]) qi++;
      }
      return qi === q.length;
    },
    openEnv(svc) {
      this.envServiceName = svc.name;
      this.envRows = [];
      this.envLoading = true;
      this.envVisible = true;
      // 实时读 K8s Deployment spec（设计决策：envs 不再随列表/SSE 携带）
      const url = '/api/deploy/service-info/envs?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(svc.name);
      ajax('GET', url, null, (r) => {
        this.envLoading = false;
        if (r.code === 200 && r.data) {
          this.envRows = (r.data.envs || []).map(e => ({ name: e.name, value: e.value || '', source: e.source || '' }));
        } else {
          // 回退：列表/快照里已有的 envs（YAML 回退路径仍携带）
          this.envRows = (svc.envs || []).map(e => ({ name: e.name, value: e.value || '', source: e.source || '' }));
          ElementPlus.ElMessage.warning((r.msg || '读取环境变量失败') + '，已展示快照数据');
        }
      });
    },
    openYaml(row) {
      const url = '/api/deploy/service-info/yaml?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(row.name);
      ajax('GET', url, null, (r) => {
        this.yamlFile = (r.data || {}).file || '';
        this.yamlContent = (r.data || {}).content || '';
        this.yamlVisible = true;
      });
    },

    // ─── 日志目录（SSH 直连 NFS）───────────────────────

    openLogFiles(svc) {
      this.lfServiceName = svc.name;
      this.lfPods = svc.pods || [];
      this.lfFiles = [];
      this.lfPath = '';
      this.lfVisible = true;
      this.loadLogFiles();
    },
    // 路径仅展示末两级目录：{项目}-{环境}/{服务目录}
    lfShortPath() {
      const parts = (this.lfPath || '').split('/').filter(Boolean);
      return parts.slice(-2).join('/');
    },
    loadLogFiles() {
      this.lfLoading = true;
      const url = '/api/deploy/service-info/logfiles?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(this.lfServiceName);
      ajax('GET', url, null, (r) => {
        this.lfLoading = false;
        if (r.code === 200 && r.data) {
          this.lfPath = r.data.path || '';
          this.lfFiles = r.data.list || [];
          if (r.data.message) ElementPlus.ElMessage.warning(r.data.message);
        } else {
          ElementPlus.ElMessage.error(r.msg || '读取日志目录失败');
        }
      });
    },
    // 文件名包含任一运行中 Pod 名则返回该 Pod 名（用于着色），否则返回空串
    lfRunningPod(fileName) {
      const pods = (this.lfPods || []).filter(p => p.phase === 'Running' && !p.reason);
      for (const p of pods) {
        if (p.name && fileName.indexOf(p.name) !== -1) return p.name;
      }
      return '';
    },
    viewLogfile(row) {
      this.lfContentFile = row.name;
      this.lfContent = '';
      this.lfContentLoading = true;
      this.lfContentVisible = true;
      const url = '/api/deploy/service-info/logfile/content?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(this.lfServiceName)
        + '&file=' + encodeURIComponent(row.name);
      ajax('GET', url, null, (r) => {
        this.lfContentLoading = false;
        if (r.code === 200 && r.data) {
          this.lfContent = r.data.content || '';
          // 加载完成滚动到底部（日志最新内容在末尾）
          this.$nextTick(() => {
            const box = this.$refs.lfContentBox;
            if (box) box.scrollTop = box.scrollHeight;
          });
        } else {
          this.lfContentVisible = false;
          ElementPlus.ElMessage.error(r.msg || '读取文件失败');
        }
      });
    },
    downloadLogfile(row) {
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject, env: this.selectedEnv,
        service: this.lfServiceName, file: row.name, token: token,
      });
      window.open('/api/deploy/service-info/logfile/download?' + params.toString());
    },

    // ─── Nacos 配置 ───────────────────────────────────────

    // 点击直接展示 {服务名}.yaml 配置内容（无列表/搜索）
    openGlobalNacos() {
      this.configRow = { dataId: 'application.yaml', group: 'DEFAULT_GROUP' };
      this.configContent = '';
      this.configEditMode = false;
      this.configSearch = '';
      this.matchCount = 0;
      this.configOriginal = '';
      this.configNotFound = false;
      this.configIsNew = false;
      this.diffVisible = false;
      this.diffRows = [];
      this.diffStats = { added: 0, removed: 0, modified: 0 };
      this.configEditorVisible = true;
      this.loadConfigContent();
    },
    openNacos(row) {
      this.configRow = { dataId: (row.name || '') + '.yaml', group: 'DEFAULT_GROUP' };
      this.configContent = '';
      this.configEditMode = false;
      this.configSearch = '';
      this.matchCount = 0;
      this.configOriginal = '';
      this.configNotFound = false;
      this.configIsNew = false;
      this.diffVisible = false;
      this.diffRows = [];
      this.diffStats = { added: 0, removed: 0, modified: 0 };
      this.configEditorVisible = true;
      this.loadConfigContent();
    },
    loadConfigContent() {
      if (!this.configRow) return;
      this.configLoading = true;
      const url = '/api/deploy/service-info/nacos/config?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv)
        + '&dataId=' + encodeURIComponent(this.configRow.dataId)
        + '&group=' + encodeURIComponent(this.configRow.group || 'DEFAULT_GROUP')
        + (this.configRow && this.configRow.global ? '&global=1' : '');
      ajax('GET', url, null, (r) => {
        this.configLoading = false;
        if (r.code === 200) {
          this.configContent = (r.data || {}).content || '';
          this.configOriginal = this.configContent;
          this.configNotFound = false;
          this.configIsNew = false;
        } else if (r.code === 404) {
          // 配置不存在：引导新增
          this.configContent = '';
          this.configOriginal = '';
          this.configNotFound = true;
        } else {
          ElementPlus.ElMessage.error(r.msg || '加载配置失败');
        }
      });
    },
    // ─── 配置查看渲染：hljs 语法高亮 + 搜索关键字 mark 高亮 ───────

    renderConfigView() {
      this.$nextTick(() => {
        const code = this.$refs.configCode;
        if (!code) return;
        code.innerHTML = this._highlightHtml(this.configContent || '');

        // 搜索高亮：遍历文本节点包裹 mark（不破坏 hljs 标签）
        this.matchCount = 0;
        const kw = (this.configSearch || '').trim();
        if (kw) {
          const lowerKw = kw.toLowerCase();
          const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT, null);
          const nodes = [];
          while (walker.nextNode()) nodes.push(walker.currentNode);
          nodes.forEach((node) => {
            const txt = node.nodeValue;
            const lower = txt.toLowerCase();
            let idx = lower.indexOf(lowerKw);
            if (idx === -1) return;
            const frag = document.createDocumentFragment();
            let last = 0;
            while (idx !== -1) {
              frag.appendChild(document.createTextNode(txt.slice(last, idx)));
              const mark = document.createElement('mark');
              mark.className = 'svc-search-mark';
              mark.textContent = txt.slice(idx, idx + kw.length);
              frag.appendChild(mark);
              this.matchCount++;
              last = idx + kw.length;
              idx = lower.indexOf(lowerKw, last);
            }
            frag.appendChild(document.createTextNode(txt.slice(last)));
            node.parentNode.replaceChild(frag, node);
          });
          this.$nextTick(() => {
            const first = code.querySelector('mark.svc-search-mark');
            if (first) first.scrollIntoView({ block: 'center' });
          });
        }
      });
    },

    escapeHtml(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    _highlightHtml(text) {
      let html = '';
      if (window.hljs) {
        try { html = window.hljs.highlight(text, { language: 'yaml' }).value; } catch (e) { html = ''; }
      }
      if (!html) html = this.escapeHtml(text);
      return html;
    },

    // 编辑模式高亮层渲染（末尾补换行，保证最后空行高度对齐）
    renderEditView() {
      this.$nextTick(() => {
        const code = this.$refs.configCodeEdit;
        if (!code) return;
        code.innerHTML = this._highlightHtml(this.configContent || '') + '\n';
      });
    },

    // textarea 滚动同步到高亮层
    syncCfgGutter(src) {
      const gutter = this.$refs.cfgGutter;
      const el = src === 'pre' ? this.$refs.configPre : this.$refs.configTextarea;
      if (!el) return;
      if (gutter) gutter.scrollTop = el.scrollTop;
      // 编辑模式：高亮层与 textarea 同步滚动
      if (src === 'edit' && el.parentNode) {
        const pre = el.parentNode.querySelector('.svc-editor-pre');
        if (pre) { pre.scrollTop = el.scrollTop; pre.scrollLeft = el.scrollLeft; }
      }
    },

    // 内容框右上角复制：复制完整配置内容
    copyConfigContent() {
      const text = this.configContent || '';
      const done = () => ElementPlus.ElMessage.success('已复制到剪贴板');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => this._fallbackCopy(text, done));
      } else {
        this._fallbackCopy(text, done);
      }
    },
    _fallbackCopy(text, done) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        done();
      } catch (e) {
        ElementPlus.ElMessage.error('复制失败');
      }
      document.body.removeChild(ta);
    },

    onConfigDialogClose() {
      this.configEditMode = false;
      this.configSearch = '';
      this.matchCount = 0;
      this.configNotFound = false;
      this.diffVisible = false;
    },

    // 取消编辑：新增态（配置原本不存在）回退到空状态引导
    cancelConfigEdit() {
      this.configEditMode = false;
      if (this.configIsNew) {
        this.configContent = '';
        this.configNotFound = true;
      }
    },

    // 配置不存在时新增：dataId 已自动生成（{服务名}.yaml），内容从空开始
    createNewConfig() {
      this.configOriginal = '';
      this.configContent = '';
      this.configNotFound = false;
      this.configEditMode = true;
      this.configIsNew = true;
    },

    // 发布前先弹出行级 diff 对比（参考 Nginx 配置保存对比逻辑）；新增配置无旧内容，不对比直接发布
    publishConfig() {
      if (!this.configRow) return;
      if (this.configIsNew) {
        this.doPublish();
        return;
      }
      const diff = this._computeDiff(
        (this.configOriginal || '').split('\n'),
        (this.configContent || '').split('\n'),
      );
      if (!diff.stats.added && !diff.stats.removed && !diff.stats.modified) {
        ElementPlus.ElMessage.warning('内容没有变化，无需发布');
        return;
      }
      this.diffRows = diff.rows;
      this.diffStats = diff.stats;
      this.diffVisible = true;
    },
    doPublish() {
      this.publishing = true;
      ajax('POST', '/api/deploy/service-info/nacos/config', {
        project: this.selectedProject,
        env: this.selectedEnv,
        dataId: this.configRow.dataId,
        group: this.configRow.group || 'DEFAULT_GROUP',
        content: this.configContent,
        global: !!(this.configRow && this.configRow.global),
      }, (r) => {
        this.publishing = false;
        if (r.code === 200) {
          ElementPlus.ElMessage.success('配置已发布');
          this.diffVisible = false;
          this.configOriginal = this.configContent;
          this.configIsNew = false;
          this.configEditMode = false;
        } else {
          ElementPlus.ElMessage.error(r.msg || '发布失败');
        }
      });
    },

    // ─── 行级 diff（与 NginxPage 同算法 + 大文件优化）─────────────
    // 性能关键：先裁掉公共前/后缀，仅对中间变化区做 LCS；
    // 展示层折叠相同行（变更前后各留 3 行上下文），避免大配置渲染全量 DOM 卡死页面

    _computeDiff(oldLines, newLines) {
      // 1. 裁公共前缀
      let start = 0;
      const minLen = Math.min(oldLines.length, newLines.length);
      while (start < minLen && oldLines[start] === newLines[start]) start++;
      // 2. 裁公共后缀
      let oldEnd = oldLines.length, newEnd = newLines.length;
      while (oldEnd > start && newEnd > start && oldLines[oldEnd - 1] === newLines[newEnd - 1]) { oldEnd--; newEnd--; }

      const stats = { added: 0, removed: 0, modified: 0 };
      const rows = [];
      // 前缀（same）
      for (let i = 0; i < start; i++) {
        rows.push({ type: 'same', oldText: oldLines[i], newText: newLines[i], oldLn: i + 1, newLn: i + 1 });
      }
      // 中间变化区
      const midOld = oldLines.slice(start, oldEnd);
      const midNew = newLines.slice(start, newEnd);
      const mid = Math.max(midOld.length, midNew.length) > 1500
        ? this._simpleDiff(midOld, midNew)
        : this._lcsDiff(midOld, midNew);
      stats.added += mid.stats.added;
      stats.removed += mid.stats.removed;
      stats.modified += mid.stats.modified;
      mid.rows.forEach((r) => {
        if (r.oldLn !== '') r.oldLn += start;
        if (r.newLn !== '') r.newLn += start;
        rows.push(r);
      });
      // 后缀（same）
      for (let i = oldEnd; i < oldLines.length; i++) {
        const j = i - oldEnd + newEnd;
        rows.push({ type: 'same', oldText: oldLines[i], newText: newLines[j], oldLn: i + 1, newLn: j + 1 });
      }
      return { rows: this._collapseSameRows(rows), stats };
    },

    // 折叠连续相同行：变更前后各保留 ctx 行上下文，其余折成占位行
    _collapseSameRows(rows, ctx = 3) {
      const keep = new Array(rows.length).fill(false);
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].type !== 'same') {
          const lo = Math.max(0, i - ctx);
          const hi = Math.min(rows.length - 1, i + ctx);
          for (let j = lo; j <= hi; j++) keep[j] = true;
        }
      }
      const out = [];
      let i = 0;
      while (i < rows.length) {
        if (keep[i]) { out.push(rows[i]); i++; continue; }
        let j = i;
        while (j < rows.length && !keep[j]) j++;
        out.push({ type: 'fold', count: j - i });
        i = j;
      }
      return out;
    },

    // LCS 行级 diff（仅用于中间变化区）
    _lcsDiff(oldLines, newLines) {
      const m = oldLines.length, n = newLines.length;
      // 构建 LCS 表
      const dp = [];
      for (let i = 0; i <= m; i++) dp[i] = new Uint16Array(n + 1);
      for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
          dp[i][j] = oldLines[i - 1] === newLines[j - 1]
            ? dp[i - 1][j - 1] + 1
            : Math.max(dp[i - 1][j], dp[i][j - 1]);
        }
      }
      // 回溯生成 diff
      const stats = { added: 0, removed: 0, modified: 0 };
      const stack = [];
      let oi = m, ni = n;
      while (oi > 0 || ni > 0) {
        if (oi > 0 && ni > 0 && oldLines[oi - 1] === newLines[ni - 1]) {
          stack.push({ type: 'same', oldText: oldLines[oi - 1], newText: newLines[ni - 1], oldLn: oi, newLn: ni });
          oi--; ni--;
        } else if (ni > 0 && (oi === 0 || dp[oi][ni - 1] >= dp[oi - 1][ni])) {
          stack.push({ type: 'added', oldText: '', newText: newLines[ni - 1], oldLn: '', newLn: ni });
          stats.added++;
          ni--;
        } else {
          stack.push({ type: 'removed', oldText: oldLines[oi - 1], newText: '', oldLn: oi, newLn: '' });
          stats.removed++;
          oi--;
        }
      }
      stack.reverse();
      // 合并相邻 removed 块 + added 块 为 modified
      const rows = [];
      let i = 0;
      while (i < stack.length) {
        const removedBlock = [];
        while (i < stack.length && stack[i].type === 'removed') { removedBlock.push(stack[i]); i++; }
        const addedBlock = [];
        while (i < stack.length && stack[i].type === 'added') { addedBlock.push(stack[i]); i++; }
        if (removedBlock.length && addedBlock.length) {
          const pair = Math.min(removedBlock.length, addedBlock.length);
          for (let p = 0; p < pair; p++) {
            rows.push({
              type: 'modified',
              oldText: removedBlock[p].oldText, newText: addedBlock[p].newText,
              oldLn: removedBlock[p].oldLn, newLn: addedBlock[p].newLn,
            });
            stats.modified++;
            stats.removed--;
            stats.added--;
          }
          for (let p = pair; p < removedBlock.length; p++) rows.push(removedBlock[p]);
          for (let p = pair; p < addedBlock.length; p++) rows.push(addedBlock[p]);
        } else {
          rows.push(...removedBlock, ...addedBlock);
        }
      }
      return { rows, stats };
    },
    _simpleDiff(oldLines, newLines) {
      const rows = [];
      const stats = { added: 0, removed: 0, modified: 0 };
      const maxLen = Math.max(oldLines.length, newLines.length);
      for (let i = 0; i < maxLen; i++) {
        const oldLine = i < oldLines.length ? oldLines[i] : null;
        const newLine = i < newLines.length ? newLines[i] : null;
        if (oldLine === null) {
          rows.push({ type: 'added', oldText: '', newText: newLine, oldLn: '', newLn: i + 1 });
          stats.added++;
        } else if (newLine === null) {
          rows.push({ type: 'removed', oldText: oldLine, newText: '', oldLn: i + 1, newLn: '' });
          stats.removed++;
        } else if (oldLine === newLine) {
          rows.push({ type: 'same', oldText: oldLine, newText: newLine, oldLn: i + 1, newLn: i + 1 });
        } else {
          rows.push({ type: 'modified', oldText: oldLine, newText: newLine, oldLn: i + 1, newLn: i + 1 });
          stats.modified++;
        }
      }
      return { rows, stats };
    },

    // ─── 通用 ─────────────────────────────────────────────

    copyText(text, label) {
      const done = () => ElementPlus.ElMessage.success((label || '内容') + ' 已复制');
      const fallback = () => {
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          done();
        } catch (e) {
          ElementPlus.ElMessage.warning('复制失败，请手动选择复制');
        }
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(String(text || '')).then(done).catch(fallback);
      } else {
        fallback();
      }
    },
  },
  beforeUnmount() {
    this.closeEnvBuildStream();
    this.closeLogStream();
    this.closeSvcStream();
    if (this._cfgKeyHandler) {
      document.removeEventListener('keydown', this._cfgKeyHandler);
      this._cfgKeyHandler = null;
    }
  },
  created() {
    // 日志弹窗键盘事件（Ctrl+F 聚焦搜索 / ESC 退出全屏）；capture 捕获阶段注册，
    // 保证先于弹窗/下拉自身的 document 级 ESC 处理执行
    window.addEventListener('keydown', this.onLogKeydown, true);
    this.loadProjects();
    // 查看模式下 Ctrl+F 聚焦弹窗内搜索框；Ctrl+A 仅选中内容区（编辑模式走 textarea 原生全选）
    this._cfgKeyHandler = (e) => {
      if (!this.configEditorVisible || this.configEditMode) return;
      const combo = e.ctrlKey || e.metaKey;
      if (!combo) return;
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        const inp = this.$refs.configSearchInput;
        if (inp && inp.focus) inp.focus();
      } else if ((e.key === 'a' || e.key === 'A') && !this.configNotFound) {
        const pre = this.$refs.configPre;
        if (pre) {
          e.preventDefault();
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.selectAllChildren(pre);
        }
      }
    };
    document.addEventListener('keydown', this._cfgKeyHandler);
  },
  unmounted() {
    window.removeEventListener('keydown', this.onLogKeydown, true);
  },
};

// ── 服务信息页样式 ──
(function() {
  // 带版本号：样式改动后强制覆盖旧节点，避免硬刷新后旧 CSS 缓存不更新
  const OLD = document.getElementById('service-info-style');
  if (OLD) OLD.remove();
  const style = document.createElement('style');
  style.id = 'service-info-style';
  style.textContent = `
.svc-log-terminal {
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  padding: 12px 14px; height: 74vh; overflow-y: auto;
  font-family: Consolas, 'Courier New', monospace; font-size: 12.5px;
  line-height: 1.6; white-space: pre-wrap; word-break: break-all;
}
.svc-yaml-pre {
  margin: 0; padding: 12px 14px; background: #f6f8fa; border-radius: 6px;
  max-height: 62vh; overflow: auto; font-size: 12.5px;
  font-family: Consolas, Menlo, monospace; white-space: pre;
}
.svc-copy-btn {
  position: absolute; top: 8px; right: 10px; z-index: 2;
  padding: 2px 10px; font-size: 12px; line-height: 1.6;
  color: #555; background: #fff; border: 1px solid #dcdfe6;
  border-radius: 4px; cursor: pointer;
}
.svc-copy-btn:hover { color: #409eff; border-color: #c6e2ff; background: #ecf5ff; }
/* 配置弹窗自适应高度：上下各留 10%，内容擑满 */
.svc-config-dialog { height: 80vh; display: flex; flex-direction: column; --el-dialog-bg-color: #0a2e3c; }
.svc-config-dialog .el-dialog { background: #0a2e3c; }
.svc-config-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-config-dialog .el-dialog__title { color: #a8bcc0 !important; font-size: 15px; }
.svc-config-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-config-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-config-dialog .el-dialog__body { background: #0a2e3c !important; padding-top: 12px; }
.svc-config-header { display: flex; align-items: center; gap: 12px; width: 100%; }
.svc-config-title { color: #a8bcc0; font-size: 15px; font-weight: 600; white-space: nowrap; }
.svc-config-count { color: #7fa3ad; font-size: 12px; white-space: nowrap; }
.svc-cfg-code { position: relative; flex: 1; min-height: 0; display: flex; border-radius: 6px; overflow: hidden; background: #0a2e3c; border: 1px solid #1c4a5e; }
.svc-cfg-gutter { width: 46px; flex-shrink: 0; overflow: hidden; background: #0d3545; color: #5c8490; text-align: right; padding: 12px 8px 12px 0; font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7; user-select: none; }
.svc-cfg-gutter-line { white-space: nowrap; }
.svc-config-dialog .el-dialog__body { flex: 1; min-height: 0; overflow: auto; }
.svc-config-dialog .el-dialog__body > div { height: 100%; display: flex; flex-direction: column; }
.svc-config-dialog .el-textarea { flex: 1; min-height: 0; display: flex; }
.svc-config-dialog .el-textarea__inner { flex: 1; height: 100%; }
/* 工具栏 / 护眼查看区 / 搜索高亮 */
.svc-cfg-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.svc-cfg-matches { color: #888; font-size: 12px; }
.svc-cfg-content { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.svc-cfg-copy-btn {
  position: absolute; top: 8px; right: 8px; z-index: 2;
  background: rgba(10, 46, 60, 0.9); border: 1px solid #2f5a6b; color: #a8bcc0;
}
.svc-cfg-copy-btn:hover { color: #d4e6ea; border-color: #3f7a8f; background: rgba(20, 60, 78, 0.95); }
/* Nacos 配置弹窗：深色适配（搜索框/普通按钮） */
.svc-config-dialog .el-input__wrapper { background: #0d3545; box-shadow: 0 0 0 1px #1c4a5e inset; }
.svc-config-dialog .el-input__inner { color: #a8bcc0; }
.svc-config-dialog .el-input__inner::placeholder { color: #5c8490; }
.svc-config-dialog .el-input__clear { color: #5c8490; }
.svc-config-dialog .el-button:not(.el-button--primary):not(.el-button--text) {
  background: #0d3545; border-color: #1c4a5e; color: #a8bcc0;
}
.svc-config-dialog .el-button:not(.el-button--primary):not(.el-button--text):hover {
  color: #d4e6ea; border-color: #3f7a8f; background: #123f52;
}
/* Nacos 配置弹窗：滚动条深色（代码区/行号栏/编辑区） */
.svc-config-dialog ::-webkit-scrollbar { width: 8px; height: 8px; }
.svc-config-dialog ::-webkit-scrollbar-track { background: #0a2e3c; }
.svc-config-dialog ::-webkit-scrollbar-thumb { background: #2f5a6b; border-radius: 4px; }
.svc-config-dialog ::-webkit-scrollbar-thumb:hover { background: #3f7a8f; }
.svc-config-pre {
  flex: 1; min-height: 0; margin: 0; padding: 12px 14px; overflow: auto;
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
}

/* 日志弹窗：整体 Nacos 配置护眼背景色 */
.svc-log-dialog { --el-dialog-bg-color: #0a2e3c; }
.svc-log-dialog .el-dialog { background: #0a2e3c; }
.svc-log-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-log-dialog .el-dialog__title { color: #a8bcc0 !important; font-size: 15px; }
.svc-log-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-log-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-log-dialog .el-dialog__body { background: #0a2e3c !important; padding-top: 12px; }
.svc-log-match { background: rgba(230, 162, 60, 0.28); }
.svc-log-time { color: #6cb6e8; }
.svc-log-method { color: #c678dd; }
.svc-log-line { color: #e5c07b; }


.svc-log-header { display: flex; align-items: center; gap: 12px; width: 100%; padding-right: 30px; }
.svc-log-title { font-size: 15px; color: #a8bcc0; white-space: nowrap; }
.svc-log-count { font-size: 12px; color: #6f94a0; background: rgba(168,188,192,.12); padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
.svc-log-header-tools { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.svc-log-fs-tip { color: #6f94a0; font-size: 12px; white-space: nowrap; }
/* 日志全屏模式：终端铺满窗口剩余高度 */
.svc-log-dialog.svc-log-fs .svc-log-terminal { height: calc(100vh - 120px); }
.svc-log-status { display: inline-flex; align-items: center; gap: 6px; color: #a8bcc0; font-size: 12px; white-space: nowrap; }
/* 日志弹窗控件全暗色：输入框/下拉/按钮去白底 */
.svc-log-dialog .el-input__wrapper {
  background: #0f3a4c;
  box-shadow: 0 0 0 1px #1c4a5e inset;
}
.svc-log-dialog .el-input__inner { color: #a8bcc0; }
.svc-log-dialog .el-input__inner::placeholder { color: #6f94a0; }
.svc-log-dialog .el-select__caret { color: #6f94a0; }
.svc-log-dialog .el-button {
  background: #0f3a4c; border-color: #1c4a5e; color: #a8bcc0;
}
.svc-log-dialog .el-button:hover:not(:disabled) { background: #14465c; border-color: #2f5a6b; color: #d4e6ea; }
.svc-log-dialog .el-button:disabled { background: #0c3140; border-color: #164052; color: #4d6d78; }
/* 滚动条与背景同色系 */
.svc-log-dialog .svc-log-terminal::-webkit-scrollbar { width: 8px; height: 8px; }
.svc-log-dialog .svc-log-terminal::-webkit-scrollbar-track { background: #0a2e3c; }
.svc-log-dialog .svc-log-terminal::-webkit-scrollbar-thumb { background: #2f5a6b; border-radius: 4px; }
.svc-log-dialog .svc-log-terminal::-webkit-scrollbar-thumb:hover { background: #3f7a8f; }
.svc-log-dialog .svc-log-terminal { scrollbar-color: #2f5a6b #0a2e3c; scrollbar-width: thin; }
/* el-select 新版触发器（.el-select__wrapper）去白底 */
.svc-log-dialog .el-select__wrapper { background: #0f3a4c; box-shadow: 0 0 0 1px #1c4a5e inset; }
.svc-log-dialog .el-select__placeholder, .svc-log-dialog .el-select__selected-item { color: #a8bcc0; }
.svc-log-dialog .el-select__caret.el-icon, .svc-log-dialog .el-input__clear { color: #6f94a0; }
/* 下拉弹出层暗色（popper teleport 到 body，用 popper-class 单独着色） */
.svc-log-popper.el-popper { background: #0f3a4c; border: 1px solid #1c4a5e; }
.svc-log-popper .el-popper__arrow::before { background: #0f3a4c; border-color: #1c4a5e; }
.svc-log-popper .el-select-dropdown__item { color: #a8bcc0; }
.svc-log-popper .el-select-dropdown__item.is-hovering, .svc-log-popper .el-select-dropdown__item:hover { background: #14465c; color: #d4e6ea; }
.svc-log-popper .el-select-dropdown__item.is-selected { color: #6cb6e8; font-weight: 600; }
.svc-log-popper .el-scrollbar__thumb { background: #2f5a6b; }
.svc-log-popper { scrollbar-color: #2f5a6b #0f3a4c; }


.bp-log-box {
  background: #0a2e3c;
  color: #a8bcc0;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 12px;
  line-height: 1.7;
  padding: 14px 18px;
  border-radius: 6px;
  height: calc(100vh - 210px);
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.bp-drawer {
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.28) !important;
  border-left: 3px solid #409eff;
}
.bp-drawer .el-drawer__header {
  background: #f0f6ff;
  border-bottom: 1px solid #d9e6f5;
  margin-bottom: 0;
  padding: 14px 20px;
}
.bp-drawer .el-drawer__body {
  background: #fafbfc;
  padding: 20px;
}
.bp-drawer .el-step__head,
.bp-drawer .el-step__title {
  cursor: pointer;
}
.bp-drawer .el-step__head:hover .el-step__icon {
  transform: scale(1.15);
  box-shadow: 0 0 0 4px rgba(64, 158, 255, 0.15);
}
.bp-drawer .el-step__title:hover {
  color: #409eff;
}
.bp-drawer .el-step__icon {
  transition: transform .15s, box-shadow .15s;
}
.bp-step-overview {
  font-size: 16px;
  line-height: 1;
}
.bp-drawer .el-step.bp-step-selected .el-step__icon {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.45);
  border-color: #409eff;
}
.bp-drawer .el-step.bp-step-selected .el-step__title {
  color: #409eff;
  font-weight: 600;
}
.build-dialog {
  height: 75vh;              /* 上留 10vh + 高 75vh = 下留 15vh */
  margin-top: 10vh !important;
  margin-bottom: 15vh !important;
  display: flex;
  flex-direction: column;
}
.build-dialog .el-dialog__header {
  flex-shrink: 0;
}
.build-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
}
.build-dialog .el-dialog__body .build-two-col {
  flex: 1;
  min-height: 0;
}
.build-dialog .el-dialog__footer {
  flex-shrink: 0;
}
.build-scope-box {
  width: 100%;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background: #fafafa;
  padding: 8px;
}
.build-scope-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 10px 8px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
}
.build-scope-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 412px;
  overflow-y: auto;
}
.build-two-col {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  min-height: 0;
}
.build-two-col .build-col {
  display: flex; flex-direction: column; min-height: 0; overflow: hidden;
}
.build-two-col .build-col-head { flex-shrink: 0; }
.build-two-col .svc-branch-tree {
  flex: 1; min-height: 0; max-height: none;
  overflow-y: auto;
}
.build-two-col .build-scope-list {
  flex: 1; min-height: 0; max-height: none;
}
.build-col {
  border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; background: #fafbfc;
  min-width: 0;
}
.build-col-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #ebeef5;
}
.build-col-title { font-size: 13.5px; font-weight: 600; color: #303133; }
.svc-branch-pane { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.svc-branch-pane .svc-branch-list { flex: 1; }
.svc-branch-group {
  font-size: 11.5px; color: #909399; background: #f5f7fa;
  padding: 4px 10px; position: sticky; top: 0; z-index: 1;
  border-bottom: 1px solid #ebeef5;
}
.svc-branch-recent-tag {
  background: #fdf6ec; color: #e6a23c; font-size: 10.5px; border-radius: 3px;
  padding: 0 4px; margin-right: 6px;
}
.svc-branch-item.recent { background: #fdf6ec; }
.svc-branch-item.recent:hover { background: #f5e7d0; }
.svc-col-loading { color: #909399; font-size: 12.5px; padding: 24px 0; text-align: center; }
.svc-col-empty { color: #c0c4cc; font-size: 12px; padding: 24px 0; text-align: center; }
/* 左栏分支平铺列表：直接展示全部，超出滚动 */
.svc-branch-list {
  flex: 1; min-height: 0; overflow-y: auto;
  border: 1px solid #e4e7ed; border-radius: 4px; background: #fff;
}
.svc-branch-item {
  padding: 6px 10px; font-family: monospace; font-size: 12.5px; color: #606266;
  cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  border-bottom: 1px solid #f0f2f5;
}
.svc-branch-item:hover { background: #f5f7fa; }
.svc-branch-item.active { background: #ecf5ff; color: #409eff; font-weight: 500; }
/* 右栏服务列表：直接铺满，独立滚动 */
.svc-service-list {
  flex: 1; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: 6px;
}
.svc-service-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px; border: 1px solid #e4e7ed; border-radius: 4px; background: #fff;
}
.svc-branch-tree {
  border: 1px solid #e4e7ed; border-radius: 4px; padding: 8px; background: #fff;
  max-height: 260px; overflow-y: auto;
}
.svc-branch-tree .el-tree { background: transparent; }
.svc-toolbar-lastbuild {
  display: flex; align-items: center; gap: 6px; margin-left: auto;
  font-size: 12px; color: #606266; cursor: pointer; user-select: none;
  background: #f4f4f5; border-radius: 6px; padding: 4px 10px;
  transition: box-shadow .15s;
}
.svc-toolbar-lastbuild:hover { box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.15); }
.svc-lb-label { color: #909399; flex-shrink: 0; }
.svc-lb-user { color: #303133; font-weight: 500; }
.svc-lb-branch { color: #409eff; font-family: monospace; }
.svc-lb-time { color: #c0c4cc; }
/* 工具栏与内容区之间的虚线分割线 */
.svc-toolbar-divider {
  border-top: 1px dashed #dcdfe6;
  margin: 0 0 12px;
}
/* 工具栏运行状态指示器：监听环境构建 SSE，无任务灰显，有任务橙色高亮 */
.svc-run-status {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid #e4e7ed; background: #fafafa; border-radius: 6px;
  padding: 4px 10px; font-size: 12px; color: #909399;
  white-space: nowrap; user-select: none;
}
.svc-run-status.svc-run-active {
  border-color: #f3d19e; background: #fdf6ec; cursor: pointer;
  transition: box-shadow .15s;
}
.svc-run-status.svc-run-active:hover { box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.18); }
.svc-run-text { color: #e6a23c; font-weight: 600; }
.svc-run-idle { color: #909399; }
.svc-active-build {
  display: flex; align-items: center; gap: 8px;
  background: #fdf6ec; border: 1px solid #f3d19e; border-radius: 6px;
  padding: 7px 12px; margin-bottom: 8px; cursor: pointer;
  transition: box-shadow .15s;
}
.svc-active-build:hover { box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.18); }
.svc-active-dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: #e6a23c; flex-shrink: 0;
  animation: svc-blink 1s ease-in-out infinite;
}
@keyframes svc-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.svc-active-label { color: #e6a23c; font-weight: 600; font-size: 12.5px; flex-shrink: 0; }
.svc-active-no { font-family: Consolas, monospace; color: #303133; font-weight: 500; font-size: 12.5px; }
.svc-active-branch { color: #909399; font-size: 12px; }
.svc-active-tip { margin-left: auto; color: #c0c4cc; font-size: 11.5px; flex-shrink: 0; }
.svc-env-builds {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px;
}
.svc-env-builds-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.svc-env-builds-list { display: flex; flex-direction: column; gap: 6px; }
.svc-env-build { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #606266; }
.svc-env-build-type { background: #ecf5ff; color: #409eff; border-radius: 4px; padding: 1px 6px; font-size: 11px; flex-shrink: 0; }
.svc-env-build-no { font-family: Consolas, monospace; color: #303133; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.svc-env-build-branch { color: #909399; flex-shrink: 0; }
.svc-env-build-status { font-weight: 500; flex-shrink: 0; }
.svc-env-build-status.bs-success { color: #67c23a; }
.svc-env-build-status.bs-running, .svc-env-build-status.bs-pending { color: #e6a23c; }
.svc-env-build-status.bs-failed { color: #f56c6c; }
.svc-env-build-time { margin-left: auto; color: #c0c4cc; font-size: 11.5px; flex-shrink: 0; }
.svc-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  min-height: 80px;
}
.svc-card {
  border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px 14px;
  background: #fff; transition: box-shadow .2s, transform .2s;
}
.svc-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.08); transform: translateY(-1px); }
.svc-card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.svc-card-name { font-weight: bold; font-size: 14px; color: #303133; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.svc-card-replicas { font-size: 12px; color: #606266; background: #f0f2f5; padding: 1px 8px; border-radius: 10px; flex-shrink: 0; }
.svc-card-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.svc-card-dot.ok { background: #67c23a; }
.svc-card-dot.warn { background: #e6a23c; }
.svc-card-dot.err { background: #f56c6c; }
.svc-card-dot.off { background: #c0c4cc; }
.svc-card-row { display: flex; gap: 8px; margin-bottom: 6px; font-size: 13px; align-items: flex-start; }
.svc-card-label { color: #909399; width: 34px; flex-shrink: 0; line-height: 22px; }
.svc-card-value { flex: 1; min-width: 0; line-height: 22px; color: #606266; }
.svc-card-image { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.svc-card-actions { border-top: 1px dashed #ebeef5; margin-top: 8px; padding-top: 8px; display: flex; gap: 4px; }
.svc-empty { padding: 40px 0; text-align: center; }
/* 首次进入、未选环境时的引导提示 */
.svc-empty-hint {
  grid-column: 1 / -1; padding: 80px 0;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.svc-empty-icon { font-size: 44px; line-height: 1; opacity: .7; margin-bottom: 8px; }
.svc-empty-text { font-size: 15px; color: #606266; font-weight: 500; }
.svc-empty-sub { font-size: 13px; color: #c0c4cc; }
.svc-config-pre code { background: transparent; font-family: inherit; font-size: inherit; }
/* hljs 深青蓝底配色（与部署日志同款护眼色） */
.svc-config-pre .hljs-comment, .svc-config-pre .hljs-meta { color: #6a9955; }
.svc-config-pre .hljs-attr, .svc-config-pre .hljs-attribute { color: #9cdcfe; }
.svc-config-pre .hljs-string { color: #ce9178; }
.svc-config-pre .hljs-number, .svc-config-pre .hljs-literal { color: #b5cea8; }
.svc-config-pre .hljs-bullet, .svc-config-pre .hljs-section { color: #569cd6; }
.svc-config-pre .hljs-title { color: #dcdcaa; }
.svc-search-mark { background: #e6a23c; color: #1e1e1e; border-radius: 2px; padding: 0 1px; }
/* 配置不存在空状态 */
.svc-cfg-empty {
  flex: 1; min-height: 300px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: #fafafa; border: 1px dashed #dcdfe6; border-radius: 6px;
}
/* 编辑模式：透明 textarea 叠在高亮层上，输入即实时语法高亮 */
.svc-editor-wrap { position: relative; flex: 1; min-height: 0; }
.svc-editor-wrap .svc-editor-pre { position: absolute; inset: 0; overflow: hidden; }
.svc-editor-textarea {
  position: absolute; inset: 0; width: 100%; height: 100%;
  padding: 12px 14px; margin: 0; border: none; outline: none; resize: none;
  background: transparent; color: transparent; caret-color: #a8bcc0;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
  white-space: pre; overflow: auto;
}
.svc-editor-textarea::selection { background: rgba(47, 90, 107, 0.9); color: transparent; }
/* diff 折叠占位行 */
.diff-fold-cell {
  text-align: center; padding: 4px 0; font-size: 12px;
  color: #909399; background: #fafafa; border-top: 1px solid #ebeef5; border-bottom: 1px solid #ebeef5;
}

/* ═══ 环境收藏栏（按用户落库，页面专属前缀 serviceinfo-）═══ */
/* .main 可视高 = 100vh - topbar(56) - padding上下(48)；收藏栏铺满该高度，主区仍可滚动 */
.serviceinfo-layout {
  display: flex; width: 100%; gap: 16px; align-items: stretch;
  min-height: calc(100vh - 104px);
}
.serviceinfo-favbar {
  flex: 0 0 220px; width: 220px;
  background: #fafbfc; border: 1px solid #ebeef5; border-radius: 8px;
  padding: 12px; display: flex; flex-direction: column;
  transition: flex-basis .2s ease, width .2s ease, padding .2s ease;
}
.serviceinfo-favbar.collapsed { flex: 0 0 44px; width: 44px; padding: 12px 6px; }
.serviceinfo-favhead { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.serviceinfo-favbar.collapsed .serviceinfo-favhead { justify-content: center; }
.serviceinfo-favtitle { font-size: 14px; font-weight: 600; color: #303133; white-space: nowrap; }
.serviceinfo-favbar.collapsed .serviceinfo-favtitle { display: none; }
.serviceinfo-favtoggle { font-size: 14px; color: #909399; padding: 2px 4px; }
.serviceinfo-favlist { display: flex; flex-direction: column; gap: 8px; flex: 1; min-height: 0; overflow-y: auto; }
.serviceinfo-favempty { color: #c0c4cc; font-size: 12px; text-align: center; padding: 24px 8px; line-height: 1.6; flex: 1; display: flex; align-items: center; justify-content: center; }
.serviceinfo-favcard {
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
  background: #fff; border: 1px solid #ebeef5; border-radius: 8px;
  padding: 8px 10px; cursor: pointer;
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.serviceinfo-favcard:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(64, 158, 255, .10); }
.serviceinfo-favcard.is-active { border-left: 4px solid #409eff; background: #ecf5ff; }
.serviceinfo-favmain { min-width: 0; flex: 1; }
.serviceinfo-favproj { font-weight: 600; font-size: 13px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.serviceinfo-favenv { font-size: 12px; color: #909399; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.serviceinfo-favdot { color: #c0c4cc; margin-right: 4px; }
.serviceinfo-favcard.is-active .serviceinfo-favdot { color: #409eff; }
.serviceinfo-favdel { color: #c0c4cc; opacity: 0; transition: opacity .15s, color .15s; flex-shrink: 0; padding: 2px 4px; }
.serviceinfo-favcard:hover .serviceinfo-favdel { opacity: 1; color: #f56c6c; }
.serviceinfo-main { flex: 1; min-width: 0; }

/* ═══ 日志目录弹窗 ═══ */
.svc-logfile-name { cursor: pointer; transition: color .15s; }
.svc-logfile-name:hover { color: #409eff; text-decoration: underline; }
.svc-logfile-name.is-running { color: #67c23a; font-weight: 600; }
.svc-logfile-name.is-running:hover { color: #85ce61; }
/* 内容查看弹窗暗色主题（与运行日志弹窗风格一致） */
.svc-logfile-dialog { --el-dialog-bg-color: #0a2e3c; }
.svc-logfile-dialog .el-dialog { background: #0a2e3c !important; }
.svc-logfile-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-logfile-dialog .el-dialog__title { color: #a8bcc0 !important; }
.svc-logfile-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-logfile-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-logfile-dialog .el-dialog__body { background: #0a2e3c !important; padding: 12px; }
.svc-logfile-dialog .el-dialog__footer { background: #0a2e3c !important; }
.svc-logfile-pre {
  height: 70vh; overflow: auto; margin: 0; padding: 12px 14px;
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-all; min-height: 120px;
}
`;

  document.head.appendChild(style);
})();

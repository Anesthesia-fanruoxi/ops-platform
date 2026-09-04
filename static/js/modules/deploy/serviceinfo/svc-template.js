// ============================================================
// 服务信息页面模板（整块 HTML 字符串）
// 模板内使用的状态/方法由同目录 mixin-*.js 提供，主文件组装
// ============================================================

window.SvcTemplate = `
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
    <el-button v-if="selectedProject && selectedEnv && canDeploy" type="danger" plain size="small"
               :loading="restartingAll" @click="restartAllServices">⟳ 重启全部服务</el-button>
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
          <span v-if="svc.version_created_at" class="svc-card-uptime"
                :title="'创建于 ' + svc.version_created_at" style="color:#909399;font-size:12px;margin-left:6px">已运行 [[ svcFormatUptime(svc.version_created_at) ]]</span>
        </span>
      </div>
      <div class="svc-card-actions">
        <el-button link type="primary" size="small" @click="openLog(svc)">日志</el-button>
        <el-button link type="primary" size="small" @click="openLogFiles(svc)">日志目录</el-button>
        <el-button link type="primary" size="small" @click="openNacos(svc)">Nacos配置</el-button>
        <el-button link type="primary" size="small" @click="openEnv(svc)">环境变量</el-button>
        <el-button link type="warning" size="small" :loading="restarting[svc.name]" @click="restartService(svc)">重启</el-button>
      </div>
    </div>
  </div>

  <!-- 运行日志弹窗（SSE 终端式；支持全屏，ESC 退出全屏） -->
  <el-dialog v-model="logVisible" width="80%" top="10vh"
             class="svc-log-dialog" :close-on-press-escape="!logFullscreen"
             :fullscreen="logFullscreen" :class="{ 'svc-log-fs': logFullscreen }" @close="onLogDialogClose">
    <template #header>
      <div class="svc-log-header">
        <span class="svc-log-title">运行日志 - [[ logServiceName ]]</span>
        <span class="svc-log-count">共 [[ logLines.length ]] 行</span>
        <span class="svc-log-status">
          <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background: streamConnected ? '#67c23a' : (logPaused ? '#e6a23c' : '#f56c6c') }"></span>
          [[ streamConnected ? '实时跟随中' : (logPaused ? '已暂停追踪' : '未连接') ]]
        </span>
        <span class="svc-log-header-tools">
          <el-input v-model="logSearchInput" ref="logSearch" size="small" style="width:260px;" clearable
                    placeholder="搜索（回车触发，自动暂停追踪）" @focus="onLogSearchFocus" @clear="commitLogSearch" @keydown.enter="onLogSearchEnter">
            <template #prefix><span class="svc-input-icon">🔍</span></template>
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
    <div class="svc-log-terminal" ref="logBox"><svc-log-lines :lines="logLines" :search-word="logSearchWord"></svc-log-lines></div>
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
          <span class="svc-logfile-name" :class="{ 'is-running': !!lfRunningPod(scope.row.name), 'is-disabled': lfTooLarge(scope.row) }"
                :title="lfTooLarge(scope.row) ? '文件超过 20MB，仅支持下载' : (lfRunningPod(scope.row.name) ? ('运行中 Pod: ' + lfRunningPod(scope.row.name) + '，点击查看内容') : '点击查看内容')"
                @click="viewLogfile(scope.row)">[[ scope.row.name ]]</span>
        </template>
      </el-table-column>
      <el-table-column prop="size_str" label="大小" width="100" align="right"></el-table-column>
      <el-table-column prop="mtime_str" label="修改时间" width="170"></el-table-column>
      <el-table-column label="操作" width="140" align="center">
        <template #default="scope">
          <el-button link type="primary" size="small" :class="{ 'lf-view-disabled': lfTooLarge(scope.row) }"
                     @click="viewLogfile(scope.row)">查看</el-button>
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
             class="svc-logfile-dialog" append-to-body>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
      <el-input v-model="lfSearchWord" size="small" style="width:260px;" clearable placeholder="搜索（高亮匹配内容）" @keydown.enter="onLfSearchEnter">
        <template #prefix><span style="font-size:13px">🔍</span></template>
      </el-input>
      <template v-if="lfSearchWord">
        <span style="color:#6f94a0;font-size:12px;white-space:nowrap;">[[ lfMatchIndices.length ? (lfSearchIdx + 1) + '/' + lfMatchIndices.length : '无匹配' ]]</span>
        <el-button size="small" :disabled="!lfMatchIndices.length" @click="lfSearchJump(-1)">↑</el-button>
        <el-button size="small" :disabled="!lfMatchIndices.length" @click="lfSearchJump(1)">↓</el-button>
      </template>
      <span style="color:#6f94a0;font-size:12px;white-space:nowrap;">共 [[ lfLines.length ]] 行[[ lfSearchWord ? '，匹配 ' + lfMatchCount + ' 行' : '' ]]</span>
    </div>
    <pre class="svc-logfile-pre" ref="lfContentBox" v-loading="lfContentLoading"
         element-loading-background="rgba(10, 46, 60, 0.9)"><div v-for="(line, i) in lfLines" :key="i" :id="'lfline-' + i" :class="{ 'lf-cur-match': isLfCurMatch(i) }" v-html="lfRenderLine(line)"></div></pre>
  </el-dialog>
  <!-- 部署配置弹窗 -->
  <el-dialog v-model="yamlVisible" :title="'部署配置 - ' + (yamlFile || '')" width="900px">
    <div style="position:relative;">
      <button class="svc-copy-btn" @click="copyText(yamlContent, 'YAML')">复制</button>
      <pre class="svc-yaml-pre">[[ yamlContent ]]</pre>
    </div>
  </el-dialog>

  <!-- Nacos 配置内容查看/编辑弹窗：深色护眼 + 语法高亮 + Ctrl+F 搜索高亮 -->
  <!-- 查看模式可点遮罩关闭；编辑模式仅 ESC / 右上角× 可关，防误触丢内容 -->
  <el-dialog v-model="configEditorVisible" width="80%" top="10vh" class="svc-config-dialog"
             :close-on-click-modal="!configEditMode" append-to-body @close="onConfigDialogClose"
             :fullscreen="configFullscreen">
    <template #header>
      <div class="svc-config-header">
        <span class="svc-config-title">Nacos 配置 - [[ configRow ? configRow.dataId : '' ]]</span>
        <span class="svc-config-count" v-if="!configNotFound">共 [[ cfgLineCount ]] 行</span>
        <span style="margin-left:auto;display:flex;gap:8px;align-items:center;">
          <el-input v-if="!configEditMode && !configNotFound" ref="configSearchInput" v-model="configSearchInput" size="small" clearable
                    placeholder="搜索（Ctrl+F，回车触发）" style="width:240px;"
                    @clear="commitConfigSearch" @keydown.enter="onConfigSearchEnter">
            <template #prefix><span class="svc-input-icon">🔍</span></template>
          </el-input>
          <span v-if="!configEditMode && !configNotFound && configSearch" class="svc-cfg-matches">
            <template v-if="matchCount > 0">[[ (cfgSearchIdx + 1) + '/' + matchCount ]]</template>
            <template v-else>无匹配</template>
          </span>
          <el-button v-if="!configEditMode && !configNotFound && configSearch" size="small" :disabled="!matchCount" @click="cfgSearchJump(-1)">↑</el-button>
          <el-button v-if="!configEditMode && !configNotFound && configSearch" size="small" :disabled="!matchCount" @click="cfgSearchJump(1)">↓</el-button>
          <el-button v-if="!configEditMode && !configNotFound && canUpdateNacos" size="small" @click="configEditMode = true">编辑</el-button>
          <el-button v-if="configEditMode" size="small" @click="cancelConfigEdit">取消编辑</el-button>
          <el-button v-if="configEditMode && canUpdateNacos" size="small" type="primary" :loading="publishing" @click="publishConfig">发布更新</el-button>
          <el-button size="small" @click="toggleConfigFullscreen">[[ configFullscreen ? '退出全屏' : '⛶ 全屏' ]]</el-button>
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
               @scroll="syncCfgGutter('pre')"><span class="svc-cfg-guides" aria-hidden="true"><i v-for="(g, gi) in cfgGuides" :key="gi" :class="'svc-cfg-guide lvl-' + g.depth" :style="g.style"></i></span><code ref="configCode" class="language-yaml"></code></pre>
          <!-- 编辑模式：透明 textarea 叠在高亮层上，输入即实时语法高亮 -->
          <div v-show="configEditMode" class="svc-editor-wrap">
            <!-- 单滚动体：textarea 唯一滚动，canvas 用 transform 平移高亮/参考线（scrollTop 赋值会被 clamp，transform 数学精确不失步） -->
            <pre class="svc-config-pre svc-editor-pre" aria-hidden="true"><span class="svc-editor-canvas" ref="cfgCanvas"><span class="svc-cfg-guides" aria-hidden="true"><i v-for="(g, gi) in cfgGuides" :key="'e' + gi" :class="'svc-cfg-guide lvl-' + g.depth" :style="g.style"></i></span><code ref="configCodeEdit" class="language-yaml"></code></span></pre>
            <textarea ref="configTextarea" :value="configContent" @input="configContent = $event.target.value"
                      @keydown="onConfigAreaKeydown" @scroll="syncCfgGutter('edit')" class="svc-editor-textarea" spellcheck="false"></textarea>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>

  <!-- 发布对比弹框（参考 Nginx 配置保存对比） -->
  <el-dialog v-model="diffVisible" width="85%" top="3vh" :close-on-click-modal="false" :close-on-press-escape="false"
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
`;

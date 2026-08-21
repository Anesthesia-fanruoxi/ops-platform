const ManagePage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div class="section-title" style="margin:0">已部署环境</div>
          <el-button type="primary" size="small" :loading="importing" @click="refreshEnvs">📥 同步</el-button>
          <el-button v-if="importing && !progressVisible" type="primary" link @click="reopenSyncLog">查看日志</el-button>
          <el-radio-group v-model="selectedProject" size="small" @change="onProjectChange" style="margin-left:8px">
            <el-radio label="">全部</el-radio>
            <el-radio v-for="p in projects" :key="p" :label="p">[[ p ]]</el-radio>
          </el-radio-group>
        </div>
        <div class="header-actions" style="display:flex;align-items:center;gap:12px">
          <!-- 前后端构建视图切换：构建状态/最近构建/构建按钮随之联动 -->
          <el-radio-group v-if="!showDeleted" v-model="buildViewType" size="small">
            <el-radio-button label="backend">后端</el-radio-button>
            <el-radio-button label="frontend">前端</el-radio-button>
          </el-radio-group>
          <el-radio-group v-model="showDeleted" size="small" @change="onTabChange">
            <el-radio-button :label="false">运行中 ([[ runningCount ]])</el-radio-button>
            <el-radio-button v-if="$auth.hasPermission('op:recycle_admin')" :label="true">回收站 ([[ deletedCount ]])</el-radio-button>
          </el-radio-group>
          <el-button v-if="!showDeleted && selectedEnvs.length > 0 && $auth.hasPermission('op:recycle')" type="danger" size="small" @click="confirmBatchRecycle">
            批量回收 ([[ selectedEnvs.length ]])
          </el-button>
          <el-button v-if="showDeleted && selectedEnvs.length > 0 && $auth.hasPermission('op:recycle_admin')" type="success" size="small" @click="confirmBatchRestore">
            批量恢复 ([[ selectedEnvs.length ]])
          </el-button>
          <el-button v-if="showDeleted && selectedEnvs.length > 0 && $auth.hasPermission('op:recycle_admin')" type="danger" size="small" @click="confirmBatchDelete">
            批量彻底删除 ([[ selectedEnvs.length ]])
          </el-button>
        </div>
      </div>

      <el-table ref="envTable" :data="sortedEnvs" v-loading="loading" stripe border style="width:100%;flex:1"
                :header-cell-style="{ background:'#f5f7fa', color:'#606266', fontWeight:'bold' }"
                @selection-change="onSelectionChange" @sort-change="onSortChange">
        <template #empty>
          <el-empty :description="showDeleted ? '回收站暂无环境' : '暂无已部署的环境'" :image-size="80" />
        </template>
        <el-table-column type="selection" width="45" align="center" />
        <el-table-column prop="project" label="项目" sortable="custom" width="120" align="center">
          <template #default="scope">
            <el-tag type="primary" size="small">[[ scope.row.project ]]</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="100" />
        <el-table-column label="域名" min-width="200">
          <template #default="scope">
            <a v-if="!showDeleted" :href="'http://' + scope.row.domain" target="_blank"
               style="color:#1890ff;text-decoration:none;font-family:monospace">
              [[ scope.row.domain ]]
            </a>
            <span v-else style="color:#909399;font-family:monospace">[[ scope.row.domain ]]</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="构建状态" width="90" align="center">
          <template #default="scope">
            <el-tag v-if="curBuild(scope.row)" :type="buildStatusType(curBuild(scope.row).status)" size="small"
                    style="cursor:pointer" @click="openProgressDrawer(curBuild(scope.row))">
              [[ buildStatusText(curBuild(scope.row).status) ]]
            </el-tag>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="最后分支" width="120">
          <template #default="scope">
            <span v-if="curBuild(scope.row)" style="font-size:12px;font-family:monospace">[[ curBuild(scope.row).branch ]]</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="执行人" width="90" align="center">
          <template #default="scope">
            <span v-if="curBuild(scope.row)" style="font-size:12px">[[ curBuild(scope.row).triggered_by ]]</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="构建时间" width="150">
          <template #default="scope">
            <span v-if="curBuild(scope.row)" style="font-size:12px;color:#909399">[[ curBuild(scope.row).created_at ]]</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showDeleted" label="删除时间" width="170">
          <template #default="scope">
            <span style="font-size:12px;color:#909399">[[ scope.row.deleted_at ]]</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" align="center" fixed="right">
          <template #default="scope">
            <template v-if="!showDeleted">
              <el-button type="primary" size="small" link @click="showDetail(scope.row)">详情</el-button>
              <el-button v-if="$auth.hasPermission('op:cicd_build')" type="warning" size="small" link @click="openBuildDialog(scope.row, buildViewType)">构建</el-button>
              <el-button v-if="$auth.hasPermission('op:recycle')" type="danger" size="small" link @click="confirmRecycle(scope.row)">回收</el-button>
            </template>
            <template v-else>
              <el-button v-if="$auth.hasPermission('op:recycle_admin')" type="success" size="small" link @click="confirmRestore(scope.row)">恢复</el-button>
              <el-button v-if="$auth.hasPermission('op:recycle_admin')" type="danger" size="small" link @click="confirmPermanentDelete(scope.row)">彻底删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 回收确认弹框 -->
    <el-dialog v-model="recycleVisible" title="确认回收环境" width="500px">
      <p style="font-size:14px;color:#303133;margin-bottom:12px">
        确定要回收环境 <strong style="color:#ff4d4f">[[ recycleEnv?.project ]]-[[ recycleEnv?.environment ]]</strong> 吗？
      </p>
      <div class="info-box">
        <div style="font-weight:600;margin-bottom:8px">以下资源将被处理：</div>
        <div style="line-height:1.8">
          <div>📦 NFS远程目录 → 移动到 /data/recycle/</div>
          <div>🗂️ Harbor镜像项目 → 删除</div>
          <div>📄 本地YAML文件 → 移动到 recycle/</div>
          <div>💾 数据库记录 → 标记为已删除（可恢复）</div>
        </div>
      </div>
      <p style="font-size:12px;color:#909399;margin-top:8px">此操作不会立即删除数据，NFS和本地文件会移入回收站目录，可手动恢复。</p>
      <template #footer>
        <el-button @click="recycleVisible = false">取消</el-button>
        <el-button type="danger" @click="executeRecycle" :loading="recycling">确认回收</el-button>
      </template>
    </el-dialog>

    <!-- 恢复确认弹框 -->
    <el-dialog v-model="restoreVisible" title="确认恢复环境" width="500px">
      <p style="font-size:14px;color:#303133;margin-bottom:12px">
        确定要恢复环境 <strong style="color:#52c41a">[[ restoreEnvData?.project ]]-[[ restoreEnvData?.environment ]]</strong> 吗？
      </p>
      <div class="info-box">
        <div style="font-weight:600;margin-bottom:8px">以下资源将被恢复：</div>
        <div style="line-height:1.8">
          <div>📦 NFS远程目录 → 从回收站还原到原位</div>
          <div>🗂️ Harbor镜像项目 → 重新创建项目 + 清理计划</div>
          <div>📄 本地YAML文件 → 从回收站还原</div>
          <div>💾 数据库记录 → 标记为未删除</div>
        </div>
      </div>
      <p style="font-size:12px;color:#909399;margin-top:8px">NFS和本地文件将从回收站目录移回原位，Harbor项目将重新创建并配置清理策略。</p>
      <template #footer>
        <el-button @click="restoreVisible = false">取消</el-button>
        <el-button type="success" @click="executeRestore" :loading="restoring">确认恢复</el-button>
      </template>
    </el-dialog>

    <!-- 彻底删除确认弹框 -->
    <el-dialog v-model="permanentDeleteVisible" title="⚠️ 彻底删除环境" width="500px">
      <p style="font-size:14px;color:#303133;margin-bottom:12px">
        确定要彻底删除环境 <strong style="color:#f5222d">[[ permanentDeleteEnv?.project ]]-[[ permanentDeleteEnv?.environment ]]</strong> 吗？
      </p>
      <div class="info-box" style="border-color:#f5222d;background:#fff2f0">
        <div style="font-weight:600;margin-bottom:8px;color:#f5222d">以下资源将被永久删除且无法恢复：</div>
        <div style="line-height:1.8">
          <div>🗑️ NFS回收站目录 → 永久删除</div>
          <div>🗑️ 本地YAML回收文件 → 永久删除</div>
          <div>🗑️ 数据库记录 → 永久删除</div>
        </div>
      </div>
      <p style="font-size:13px;color:#f5222d;margin-top:12px;font-weight:500">
        请输入 <strong>[[ permanentDeleteEnv?.project ]]-[[ permanentDeleteEnv?.environment ]]</strong> 确认删除：
      </p>
      <el-input v-model="permanentDeleteConfirmText"
                :placeholder="(permanentDeleteEnv?.project || '') + '-' + (permanentDeleteEnv?.environment || '')"
                style="margin-top:6px" />
      <template #footer>
        <el-button @click="permanentDeleteVisible = false">取消</el-button>
        <el-button type="danger" @click="executePermanentDelete"
                   :loading="permanentDeleting"
                   :disabled="permanentDeleteConfirmText !== ((permanentDeleteEnv?.project || '') + '-' + (permanentDeleteEnv?.environment || ''))">
          确认彻底删除
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量彻底删除确认弹框 -->
    <el-dialog v-model="batchDeleteVisible" title="⚠️ 批量彻底删除" width="550px">
      <p style="font-size:14px;color:#303133;margin-bottom:12px">
        确定要彻底删除选中的 <strong style="color:#f5222d">[[ selectedEnvs.length ]]</strong> 个环境吗？
      </p>
      <div class="info-box" style="border-color:#f5222d;background:#fff2f0">
        <div style="font-weight:600;margin-bottom:8px;color:#f5222d">以下环境将被永久删除且无法恢复：</div>
        <div style="line-height:1.8;max-height:200px;overflow-y:auto">
          <div v-for="env in selectedEnvsData" :key="env.id" style="padding:2px 0">
            🗑️ [[ env.project ]]-[[ env.environment ]]
          </div>
        </div>
      </div>
      <p style="font-size:13px;color:#f5222d;margin-top:12px;font-weight:500">请输入 <strong>DELETE</strong> 确认批量删除：</p>
      <el-input v-model="batchDeleteConfirmText" placeholder="输入 DELETE 确认" style="margin-top:6px" />
      <template #footer>
        <el-button @click="batchDeleteVisible = false">取消</el-button>
        <el-button type="danger" @click="executeBatchDelete"
                   :loading="batchDeleting" :disabled="batchDeleteConfirmText !== 'DELETE'">
          确认批量删除
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量回收/恢复确认弹框 -->
    <el-dialog v-model="batchConfirmVisible"
               :title="(batchConfirmAction === '回收' ? '⚠️' : '♻️') + ' 批量' + batchConfirmAction"
               width="500px">
      <p style="font-size:14px;color:#303133;margin-bottom:12px">
        确定要[[ batchConfirmAction ]]选中的 <strong>[[ selectedEnvs.length ]]</strong> 个环境吗？
      </p>
      <div class="info-box" :style="{borderColor: batchConfirmAction === '回收' ? '#f5222d' : '#52c41a', background: batchConfirmAction === '回收' ? '#fff2f0' : '#f6ffed'}">
        <div style="font-weight:600;margin-bottom:8px">以下环境将被[[ batchConfirmAction ]]：</div>
        <div style="line-height:1.8;max-height:200px;overflow-y:auto">
          <div v-for="env in selectedEnvsData" :key="env.id" style="padding:2px 0">
            [[ batchConfirmAction === '回收' ? '📦' : '♻️' ]] [[ env.project ]]-[[ env.environment ]]
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="batchConfirmVisible = false">取消</el-button>
        <el-button :type="batchConfirmAction === '回收' ? 'danger' : 'success'" @click="executeBatchConfirm" :loading="batchConfirming">
          确认批量[[ batchConfirmAction ]]
        </el-button>
      </template>
    </el-dialog>

    <!-- 构建弹窗：两栏对称（左分支 / 右构建范围），与服务信息页快捷部署一致 -->
    <el-dialog v-model="buildDialogVisible" :title="'构建' + (buildType === 'frontend' ? '前端' : '后端') + ' - ' + (buildEnv?.project || '') + '-' + (buildEnv?.environment || '')"
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
          <!-- 平铺模式：输入框选择/过滤 + 直接展示全部分支（最近分支分组） -->
          <div v-if="!branchTreeMode" class="svc-branch-pane">
            <el-input v-model="branchSearch"
                      :placeholder="'默认分支：' + buildBranch" clearable size="small"
                      @keyup.enter="applyBranchInput" @focus="onBranchFocus" style="margin-bottom:6px" />
            <div class="svc-branch-list">
              <div v-if="branchLoading" class="svc-col-loading">加载分支中...</div>
              <div v-else>
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
          <!-- 目录树模式：直接展示层级树 -->
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

    <!-- 构建进度抽屉 -->
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
      <!-- 步骤条（点击总览或步骤圈切换日志，蓝色框标识当前查看的步骤） -->
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
      <!-- 失败原因 -->
      <el-alert v-if="bpBuild && bpBuild.status === 'failed' && bpBuild.error_msg"
                :title="bpBuild.error_msg" type="error" :closable="false" show-icon style="margin-bottom:12px" />
      <!-- 日志区域 -->
      <div ref="bpLogContainer" class="bp-log-box">[[ bpLogView() || '等待日志输出...' ]]</div>
    </el-drawer>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" :title="detailEnv + ' 详细信息'" width="800px" class="manage-dialog">
      <div v-if="detailData">
        <el-tabs v-model="activeTab" @tab-change="onDetailTabChange">
          <el-tab-pane :label="'服务 (' + (detailData.deployments?.length || 0) + ')'" name="service">
            <el-input v-model="serviceFilter" placeholder="搜索服务名称" clearable size="small" style="width:240px;margin-bottom:8px" prefix-icon="Search" />
            <el-table v-if="detailData.deployments && detailData.deployments.length" :data="displayDeployments" stripe border size="small">
              <el-table-column prop="name" label="名称" />
              <el-table-column prop="replicas" label="副本数" width="70" align="center" />
              <el-table-column label="debug端口" width="90" align="center">
                <template #default="scope">
                  <span v-if="scope.row.debugPort" class="copy-cell copy-port" @dblclick="copyText(scope.row.debugPort)">[[ scope.row.debugPort ]]</span>
                </template>
              </el-table-column>
              <el-table-column label="访问端口" width="90" align="center">
                <template #default="scope">
                  <span v-if="scope.row.servicePort" class="copy-cell copy-port" @dblclick="copyText(scope.row.servicePort)">[[ scope.row.servicePort ]]</span>
                </template>
              </el-table-column>
              <el-table-column prop="image" label="镜像" min-width="260" show-overflow-tooltip />
            </el-table>
            <el-empty v-else description="暂无数据" :image-size="60" />
            <div v-if="detailData.deployments && detailData.deployments.length > 30" style="font-size:12px;color:#909399;margin-top:4px">
              共 [[ detailData.deployments.length ]] 条，显示前 30 条
            </div>
          </el-tab-pane>

          <el-tab-pane :label="'中间件 (' + (detailData.middleware?.length || 0) + ')'" name="middleware">
            <el-table v-if="detailData.middleware && detailData.middleware.length" :data="mergedMiddleware" stripe border size="small">
              <el-table-column prop="name" label="名称" />
              <el-table-column label="访问端口" width="100" align="center">
                <template #default="scope">
                  <span v-if="scope.row.nodePort" class="copy-cell copy-port" @dblclick="copyText(scope.row.nodePort)">[[ scope.row.nodePort ]]</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column label="账号" width="120">
                <template #default="scope">
                  <span v-if="scope.row.user && scope.row.user !== '-'" class="copy-cell" @dblclick="copyText(scope.row.user)">[[ scope.row.user ]]</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column label="密码" width="180">
                <template #default="scope">
                  <span v-if="scope.row.pass && scope.row.pass !== '-'" class="copy-cell" @dblclick="copyText(scope.row.pass)">[[ scope.row.pass ]]</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无数据" :image-size="60" />
          </el-tab-pane>

          <el-tab-pane label="前端构建记录" name="builds_frontend">
            <el-table v-if="envBuilds.length" :data="envBuilds" stripe border size="small">
              <el-table-column prop="build_no" label="编号" width="170" />
              <el-table-column prop="branch" label="分支" width="120" show-overflow-tooltip />
              <el-table-column label="状态" width="80" align="center">
                <template #default="s">
                  <el-tag :type="buildStatusType(s.row.status)" size="small">[[ buildStatusText(s.row.status) ]]</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="triggered_by" label="执行人" width="80" align="center" />
              <el-table-column label="耗时" width="70" align="center">
                <template #default="s">[[ s.row.duration ? Math.round(s.row.duration) + 's' : '-' ]]</template>
              </el-table-column>
              <el-table-column prop="created_at" label="创建时间" width="155" />
              <el-table-column label="操作" width="80" align="center">
                <template #default="s">
                  <el-button type="primary" size="small" link @click="viewBuildLog(s.row)">日志</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无前端构建记录" :image-size="60" />
          </el-tab-pane>

          <el-tab-pane label="后端构建记录" name="builds_backend">
            <el-table v-if="envBuilds.length" :data="envBuilds" stripe border size="small">
              <el-table-column prop="build_no" label="编号" width="170" />
              <el-table-column prop="branch" label="分支" width="120" show-overflow-tooltip />
              <el-table-column label="状态" width="80" align="center">
                <template #default="s">
                  <el-tag :type="buildStatusType(s.row.status)" size="small">[[ buildStatusText(s.row.status) ]]</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="triggered_by" label="执行人" width="80" align="center" />
              <el-table-column label="耗时" width="70" align="center">
                <template #default="s">[[ s.row.duration ? Math.round(s.row.duration) + 's' : '-' ]]</template>
              </el-table-column>
              <el-table-column prop="created_at" label="创建时间" width="155" />
              <el-table-column label="操作" width="80" align="center">
                <template #default="s">
                  <el-button type="primary" size="small" link @click="viewBuildLog(s.row)">日志</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无后端构建记录" :image-size="60" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <!-- 进度弹框（回收/恢复/同步共用） -->
    <el-dialog v-model="progressVisible"
               :title="progressDone ? (progressSuccess ? progressAction + '完成' : progressAction + '失败') : '正在' + progressAction + '...'"
               width="700px" :close-on-click-modal="false" :close-on-press-escape="false">
      <div v-if="progressProject" style="font-size:13px;color:#909399;margin-bottom:8px">
        [[ progressProject ]]-[[ progressEnv ]]
      </div>
      <div class="deploy-log" ref="progressLogContainer" style="max-height:400px;overflow-y:auto">
        <div v-for="(log, i) in progressLogs" :key="i" :class="['log-line', 'log-' + log.level.toLowerCase()]">
          <span class="log-time">[[ log.time ]]</span>
          <span :class="['log-level', 'lvl-' + log.level.toLowerCase()]">[[ log.level ]]</span>
          <span v-if="log.step" class="log-step">[[ log.step ]]</span>
          <span class="log-msg">[[ log.message ]]</span>
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="copyProgressLogs" :disabled="!progressLogs.length">📋 复制日志</el-button>
        <span v-if="progressDone" :style="{color: progressSuccess ? '#52c41a' : '#f5222d', fontWeight:'bold', fontSize:'14px'}">
          [[ progressSuccess ? '✓ 成功' : '✗ 失败' ]]
        </span>
        <span style="color:#909399;font-size:12px;margin-left:12px">共 [[ progressLogs.length ]] 行</span>
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
  `,
  data() {
    return {
      envs: [],
      projects: [],
      selectedProject: '',
      loading: false,
      importing: false,
      detailVisible: false,
      detailBuildType: 'backend',  // 详情构建记录 tab 的 前后端 过滤
      _detailEnvId: null,
      detailEnv: '',
      detailData: null,
      serviceFilter: '',
      activeTab: 'service',
      recycleVisible: false,
      recycleEnv: null,
      recycling: false,
      showDeleted: false,
      runningCount: 0,
      deletedCount: 0,
      restoreVisible: false,
      restoreEnvData: null,
      restoring: false,
      permanentDeleteVisible: false,
      permanentDeleteEnv: null,
      permanentDeleteConfirmText: '',
      permanentDeleting: false,
      selectedEnvs: [],
      batchDeleteVisible: false,
      batchDeleteConfirmText: '',
      batchDeleting: false,
      batchConfirmVisible: false,
      batchConfirmAction: '',
      batchConfirming: false,
      progressVisible: false,
      progressLogs: [],
      progressDone: false,
      progressSuccess: false,
      progressAction: '',
      progressProject: '',
      progressEnv: '',
      progressEventSource: null,
      syncEventSource: null,
      sortField: 'project',
      sortOrder: 'asc',
      // 构建弹窗
      buildDialogVisible: false,
      buildType: 'backend',  // backend / frontend（构建弹窗实际类型）
      buildViewType: 'backend',  // 页面构建视图切换：后端/前端（构建状态/构建按钮联动）
      buildEnv: null,
      buildBranch: '',
      branchTreeMode: false,
      branchTreeFilter: '',
      branchSearch: '',
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
      // 步骤实时计时（500ms 刷新一次，展示当前步骤运行时长）
      bpNow: Date.now(),
      bpTimer: null,
      // 构建记录
      envBuilds: [],
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
    };
  },
  computed: {
    selectDirsSegments() { return this.selectDirsPath ? this.selectDirsPath.split('/').filter(Boolean) : []; },
    selectDirsParent() {
      const segs = this.selectDirsSegments;
      return segs.length > 1 ? segs.slice(0, -1).join('/') : '';
    },
    // 部署步骤 waiting：后端未配置服务目录，需勾选回填后重新构建
    bpDeployWaiting() {
      return (this.bpSteps || []).some(s => s.key === 'deploy' && s.status === 'waiting');
    },
    // 全部勾选状态：所有服务开关都开启时为 true（供「全部勾选」开关联动）
    allServicesChecked() {
      return this.serviceOptions.length > 0 && this.serviceOptions.every(s => this.serviceToggles[s]);
    },
    selectedServiceCount() {
      return this.serviceOptions.filter(s => this.serviceToggles[s]).length;
    },
    // 输入框关键字：仅手动输入时过滤（回填为 placeholder，不参与过滤）
    branchKw() {
      return (this.branchSearch || '').trim().toLowerCase();
    },
    branchRecentList() {
      const kw = this.branchKw;
      const list = kw
        ? this.recentBranches.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.recentBranches.slice();
      return list.slice(0, 5);
    },
    branchAllList() {
      const kw = this.branchKw;
      const recent = this.recentBranches;
      const list = kw
        ? this.branchOptions.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.branchOptions.slice();
      return list.filter(b => !recent.includes(b));
    },
    // 分支目录树：按 / 分层构建
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
    sortedEnvs() {      var list = this.envs.slice();
      var field = this.sortField;
      var order = this.sortOrder;
      if (!field) return list;
      list.sort(function(a, b) {
        var va = a[field], vb = b[field];
        if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase(); }
        if (va < vb) return order === 'asc' ? -1 : 1;
        if (va > vb) return order === 'asc' ? 1 : -1;
        return 0;
      });
      return list;
    },
    displayDeployments() {
      const svcMap = {};
      (this.detailData?.services || []).forEach(svc => {
        svcMap[svc.name] = svc;
      });
      let list = this.detailData?.deployments || [];
      const kw = (this.serviceFilter || '').trim().toLowerCase();
      if (kw) {
        list = list.filter(dep => this.subsequenceMatch(dep.name.toLowerCase(), kw));
      } else {
        list = list.slice(0, 30);
      }
      return list.map(dep => {
        const svc = svcMap[dep.name];
        return {
          ...dep,
          debugPort: svc ? this.getPort(svc.ports, 'debug') : '',
          servicePort: svc ? this.getPort(svc.ports, 'service') : ''
        };
      });
    },
    displayMiddleware() {
      return (this.detailData?.middleware || []).slice(0, 30);
    },
    selectedEnvsData() {
      return this.selectedEnvs;
    },
    selectedEnvIds() {
      return this.selectedEnvs.map(e => e.id);
    },
    credentialRows() {
      const c = this.detailData?.credentials;
      if (!c) return [];
      return [
        { name: 'MySQL', user: c.mysql?.user || '-', pass: c.mysql?.pass || '-' },
        { name: 'Redis', user: c.redis?.user || '-', pass: c.redis?.pass || '-' },
        { name: 'RabbitMQ', user: c.rabbitmq?.user || '-', pass: c.rabbitmq?.pass || '-' },
        { name: 'Nacos', user: c.nacos?.user || '-', pass: c.nacos?.pass || '-' },
      ];
    },
    mergedMiddleware() {
      const list = this.detailData?.middleware || [];
      const c = this.detailData?.credentials || {};
      // 精确匹配：中间件名称必须完全等于凭据 key
      const match = (name) => {
        const n = name.toLowerCase();
        if (n === 'mysql') return c.mysql;
        if (n === 'redis') return c.redis;
        if (n === 'rabbitmq') return c.rabbitmq;
        if (n === 'nacos') return c.nacos;
        return null;
      };
      return list.map(mw => {
        const cred = match(mw.name);
        return {
          name: mw.name,
          nodePort: mw.nodePort || '',
          user: cred?.user || '-',
          pass: cred?.pass || '-',
        };
      });
    },
  },
  watch: {
    branchTreeFilter(v) {
      this.$refs.branchTreeRef && this.$refs.branchTreeRef.filter(v);
    },
  },
  methods: {
    loadProjects() {
      ajax('GET', '/api/admin/projects', null, (r) => {
        this.projects = (r.data || []).map(p => p.name);
      });
    },
    onTabChange() {
      this.selectedEnvs = [];
      this.showDeleted ? this.loadDeletedEnvs() : this.loadEnvs();
    },
    onProjectChange() {
      this.selectedEnvs = [];
      this.showDeleted ? this.loadDeletedEnvs() : this.loadEnvs();
    },
    onSelectionChange(rows) {
      this.selectedEnvs = rows;
    },
    onSortChange({ prop, order }) {
      if (!prop) { this.sortField = 'project'; this.sortOrder = 'asc'; }
      else {
        this.sortField = prop;
        this.sortOrder = order === 'ascending' ? 'asc' : 'desc';
      }
    },
    loadEnvs() {
      this.loading = true;
      this.selectedEnvs = [];
      let url = '/api/manage/environments/list';
      if (this.selectedProject) url += '?project=' + this.selectedProject;
      ajax('GET', url, null, (r) => {
        const d = r.data || {};
        this.envs = d.list || [];
        this.runningCount = d.running_count || 0;
        this.deletedCount = d.deleted_count || 0;
        this.loading = false;
        this.clearTableSelection();
      });
    },
    loadDeletedEnvs() {
      this.loading = true;
      this.selectedEnvs = [];
      let url = '/api/manage/environments/deleted';
      if (this.selectedProject) url += '?project=' + this.selectedProject;
      ajax('GET', url, null, (r) => {
        const d = r.data || {};
        this.envs = d.list || [];
        this.runningCount = d.running_count || 0;
        this.deletedCount = d.deleted_count || 0;
        this.loading = false;
        this.clearTableSelection();
      });
    },
    clearTableSelection() {
      this.$nextTick(() => { if (this.$refs.envTable) this.$refs.envTable.clearSelection(); });
    },
    loadRunningCount() {
      let url = '/api/manage/environments/list';
      if (this.selectedProject) url += '?project=' + this.selectedProject;
      ajax('GET', url, null, (r) => { this.runningCount = (r.data || {}).running_count || 0; });
    },
    loadDeletedCount() {
      let url = '/api/manage/environments/deleted';
      if (this.selectedProject) url += '?project=' + this.selectedProject;
      ajax('GET', url, null, (r) => { this.deletedCount = (r.data || {}).deleted_count || 0; });
    },
    refreshEnvs() {
      var self = this;
      ajax('POST', '/api/manage/environments/refresh', {}, function(r) {
        if (r.code === 200) {
          self.importing = true;
          self.progressAction = '同步';
          self.progressProject = '';
          self.progressEnv = '';
          self.progressLogs = [];
          self.progressDone = false;
          self.progressSuccess = false;
          self.progressVisible = true;
          self.connectSyncSSE();
        } else {
          showError(r.msg || '同步启动失败');
        }
      });
    },
    reopenSyncLog() {
      this.progressAction = '同步';
      this.progressProject = '';
      this.progressEnv = '';
      this.progressLogs = [];
      this.progressDone = false;
      this.progressSuccess = false;
      this.progressVisible = true;
      this.connectSyncSSE();
    },
    connectSyncSSE() {
      var self = this;
      if (self.syncEventSource) self.syncEventSource.close();
      var token = localStorage.getItem('auth_token') || '';
      var es = new EventSource('/api/deploy/stream?action=sync&token=' + encodeURIComponent(token));
      self.syncEventSource = es;
      es.onmessage = function(e) {
        var d = JSON.parse(e.data);
        if (d.done) {
          self.progressDone = true;
          self.progressSuccess = d.success !== false;
          es.close();
          self.syncEventSource = null;
          self.importing = false;
          if (self.progressSuccess) self.loadEnvs();
          return;
        }
        self.progressLogs.push(d);
        self.$nextTick(function() {
          var c = self.$refs.progressLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = function() {
        es.close();
        self.syncEventSource = null;
        self.importing = false;
        self.progressDone = true;
        self.progressSuccess = false;
        self.progressLogs.push({time:'--',level:'ERROR',message:'SSE连接失败'});
      };
    },
    subsequenceMatch(text, keyword) {
      let i = 0;
      for (let j = 0; j < text.length && i < keyword.length; j++) {
        if (text[j] === keyword[i]) i++;
      }
      return i >= keyword.length;
    },
    getPort(ports, name) {
      if (!ports || !Array.isArray(ports)) return '';
      const port = ports.find(p => p.name === name);
      return port && port.nodePort ? String(port.nodePort) : '';
    },
    showDetail(env) {
      this.detailEnv = env.project + '-' + env.environment;
      this.detailVisible = true;
      this.activeTab = 'service';
      this.serviceFilter = '';
      this.envBuilds = [];
      this._detailEnvId = env.id;
      ajax('GET', '/api/manage/environments/detail?environment=' + env.project + '-' + env.environment, null, (r) => {
        this.detailData = r.data;
      });
    },
    confirmRecycle(env) { this.recycleEnv = env; this.recycleVisible = true; },
    executeRecycle() {
      if (!this.recycleEnv) return;
      this.recycling = true;
      ajax('POST', '/api/deploy/recycle', { environment_id: this.recycleEnv.id }, (r) => {
        this.recycling = false;
        if (r.code === 200) {
          this.recycleVisible = false;
          this.openProgress(r.data.project, r.data.env, '回收');
        } else {
          showError(r.msg || '回收失败');
        }
      });
    },
    confirmRestore(env) { this.restoreEnvData = env; this.restoreVisible = true; },
    executeRestore() {
      if (!this.restoreEnvData) return;
      this.restoring = true;
      ajax('POST', '/api/deploy/restore', { environment_id: this.restoreEnvData.id }, (r) => {
        this.restoring = false;
        if (r.code === 200) {
          this.restoreVisible = false;
          this.openProgress(r.data.project, r.data.env, '恢复');
        } else {
          showError(r.msg || '恢复失败');
        }
      });
    },
    confirmPermanentDelete(env) {
      this.permanentDeleteEnv = env;
      this.permanentDeleteConfirmText = '';
      this.permanentDeleteVisible = true;
    },
    executePermanentDelete() {
      if (!this.permanentDeleteEnv) return;
      this.permanentDeleting = true;
      ajax('POST', '/api/deploy/permanent-delete', { environment_id: this.permanentDeleteEnv.id }, (r) => {
        this.permanentDeleting = false;
        if (r.code === 200) {
          this.permanentDeleteVisible = false;
          this.openProgress(r.data.project, r.data.env, '彻底删除');
        } else {
          showError(r.msg || '删除失败');
        }
      });
    },
    confirmBatchDelete() {
      if (this.selectedEnvs.length === 0) return;
      this.batchDeleteConfirmText = '';
      this.batchDeleteVisible = true;
    },
    executeBatchDelete() {
      if (this.selectedEnvs.length === 0) return;
      this.batchDeleting = true;
      ajax('POST', '/api/deploy/batch-permanent-delete', { environment_ids: this.selectedEnvIds }, (r) => {
        this.batchDeleting = false;
        if (r.code === 200) {
          this.batchDeleteVisible = false;
          this.selectedEnvs = [];
          this.openBatchProgress(r.data.task_key, r.data.count);
        } else {
          showError(r.msg || '批量删除失败');
        }
      });
    },
    confirmBatchRecycle() {
      if (this.selectedEnvs.length === 0) return;
      this.batchConfirmAction = '回收';
      this.batchConfirmVisible = true;
    },
    confirmBatchRestore() {
      if (this.selectedEnvs.length === 0) return;
      this.batchConfirmAction = '恢复';
      this.batchConfirmVisible = true;
    },
    executeBatchConfirm() {
      if (this.selectedEnvs.length === 0) return;
      this.batchConfirming = true;
      var action = this.batchConfirmAction;
      var url = action === '回收' ? '/api/deploy/batch-recycle' : '/api/deploy/batch-restore';
      ajax('POST', url, { environment_ids: this.selectedEnvIds }, (r) => {
        this.batchConfirming = false;
        if (r.code === 200) {
          this.batchConfirmVisible = false;
          this.selectedEnvs = [];
          this.openBatchProgress(r.data.task_key, r.data.count, action);
        } else {
          showError(r.msg || '批量' + action + '失败');
        }
      });
    },
    openBatchProgress(taskKey, count, action) {
      this.progressVisible = true;
      this.progressLogs = [];
      this.progressDone = false;
      this.progressSuccess = false;
      var actionLabel = action ? ('批量' + action) : '批量彻底删除';
      this.progressAction = actionLabel + '(' + count + '个)';
      this.progressProject = '';
      this.progressEnv = '';
      var sseActionMap = {'回收': 'batch-recycle', '恢复': 'batch-restore'};
      var sseAction = action ? (sseActionMap[action] || 'batch-permanent-delete') : 'batch-permanent-delete';
      this.connectProgressSSE('', '', sseAction, taskKey);
    },
    openProgress(project, env, action) {
      this.progressVisible = true;
      this.progressLogs = [];
      this.progressDone = false;
      this.progressSuccess = false;
      this.progressAction = action;
      this.progressProject = project;
      this.progressEnv = env;
      this.connectProgressSSE(project, env, action);
    },
    connectProgressSSE(project, env, action, taskKey) {
      var self = this;
      var actionMap = {'回收': 'recycle', '恢复': 'restore', '部署': 'environment', '彻底删除': 'permanent-delete'};
      var sseAction = actionMap[action] || action;
      var url = '/api/deploy/stream?action=' + sseAction;
      if (sseAction.startsWith('batch-') && taskKey) {
        url += '&task_key=' + encodeURIComponent(taskKey);
      } else {
        url += '&project=' + encodeURIComponent(project) + '&env=' + encodeURIComponent(env);
      }
      var token = localStorage.getItem('auth_token') || '';
      var es = new EventSource(url + '&token=' + encodeURIComponent(token));
      self.progressEventSource = es;
      es.onmessage = function(e) {
        try {
          var d = JSON.parse(e.data);
          if (d.done) {
            self.progressDone = true;
            self.progressSuccess = d.success !== false;
            es.close();
            if (self.progressSuccess) {
              if (action === '回收' || action === 'batch-recycle') self.loadEnvs();
              else self.loadDeletedEnvs();
            }
            return;
          }
          self.progressLogs.push(d);
          self.$nextTick(function() {
            var c = self.$refs.progressLogContainer;
            if (c) c.scrollTop = c.scrollHeight;
          });
        } catch(ex) { console.error('SSE parse error', ex); }
      };
      es.onerror = function() {
        self.progressDone = true;
        self.progressSuccess = false;
        self.progressLogs.push({time:'--',level:'ERROR',message:'连接中断'});
        es.close();
      };
    },
    closeProgress() {
      this.progressVisible = false;
      if (this.progressEventSource) { this.progressEventSource.close(); this.progressEventSource = null; }
    },
    copyProgressLogs() {
      const lines = this.progressLogs.map(l =>
        (l.time || '') + ' ' + (l.level || '') + (l.step ? ' [' + l.step + ']' : '') + ' ' + (l.message || '') + '\n'
      ).join('');
      if (!lines) return;
      const header = '[' + (this.progressProject || '') + '-' + (this.progressEnv || '') + '] ' + this.progressAction + '日志\n\n';
      this.copyText(header + lines);
    },
    // ─── CI/CD 构建 ───────────────────────────────────
    copyText(text) {
      const str = String(text);
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(str).then(() => {
          ElementPlus.ElMessage.success('已复制: ' + str);
        }).catch(() => { this._fallbackCopy(str); });
      } else {
        this._fallbackCopy(str);
      }
    },
    _fallbackCopy(str) {
      const ta = document.createElement('textarea');
      ta.value = str;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        ElementPlus.ElMessage.success('已复制: ' + str);
      } catch(e) {
        ElementPlus.ElMessage.error('复制失败');
      }
      document.body.removeChild(ta);
    },
    buildStatusType(status) {
      const map = { success: 'success', failed: 'danger', running: 'warning', pending: 'info', cancelled: 'info' };
      return map[status] || 'info';
    },
    buildStatusText(status) {
      const map = { success: '成功', failed: '失败', running: '运行中', pending: '等待', cancelled: '已取消' };
      return map[status] || status;
    },
    // ─── 构建弹窗配置记忆（localStorage 按环境区分） ───────
    _buildPrefKey(envId) {
      return 'cicd_build_pref_' + envId;
    },
    _buildPrefLoad(envId) {
      try {
        const raw = localStorage.getItem(this._buildPrefKey(envId));
        return raw ? JSON.parse(raw) : null;
      } catch (e) {
        return null;
      }
    },
    _buildPrefSave() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      const enabled = this.serviceOptions.filter(s => this.serviceToggles[s]);
      try {
        localStorage.setItem(this._buildPrefKey(this.buildEnv.id), JSON.stringify({
          branch: this.buildBranch,
          services: enabled
        }));
      } catch (e) { /* 忽略存储异常（隐私模式等） */ }
    },
    // 当前视图类型的最近构建（返回体 builds 分层：{backend, frontend}；元数据在顶层不变）
    curBuild(row) {
      return ((row.builds || {})[this.buildViewType] || null);
    },
    // 点击构建：先校验该类型模板配置并预取分支，成功后才弹出分支选择框（避免未配置时弹窗一闪而过）
    openBuildDialog(row, type) {
      this.buildType = (type === 'frontend') ? 'frontend' : 'backend';
      this.buildEnv = row;
      if (!row.project_id) { ElementPlus.ElMessage.warning('缺少项目信息'); return; }

      // 立即弹窗（git ls-remote 可能 1s+，分支异步加载不阻塞）
      this._initBuildDialog(row);
      this.buildDialogVisible = true;
      if (this.buildType === 'backend') this._loadBuildServices(row);
      // 分支异步加载：期间弹窗已可操作，显示 loading
      this.branchLoading = true;
      ajax('GET', '/api/cicd/builds/branches?project_id=' + row.project_id + '&project_type=' + this.buildType, null, (r) => {
        this.branchLoading = false;
        if (r.code === 200) {
          let branches = r.data || [];
          const lastBranch = (row.last_build && row.last_build.branch) || '';
          if (lastBranch && !branches.includes(lastBranch)) branches.unshift(lastBranch);
          this.branchOptions = branches;
          this.branchFiltered = branches;
        } else if (r.code === 400) {
          // 该类型未配置模板/无 Git 地址：收起弹窗并提示
          this.buildDialogVisible = false;
          ElementPlus.ElMessage.error(r.message || r.msg || '该项目未配置模板');
        } else {
          // 网络/服务异常：保留弹窗，分支可手动输入
          ElementPlus.ElMessage.error((r.message || r.msg || '获取分支失败') + '，可手动输入分支');
        }
      }, () => { this.branchLoading = false; });
    },

    // 初始化构建弹窗状态（恢复上次偏好 + 最近使用分支）
    _initBuildDialog(row) {
      const pref = this._buildPrefLoad(row.id);
      const lastBranch = (row.last_build && row.last_build.branch) || '';
      this.buildBranch = (pref && pref.branch) || lastBranch || 'master';
      this.recentBranches = [];
      this.recentBranchesFiltered = [];
      this.serviceToggles = {};
      this.serviceOptions = [];
      this.servicesLoaded = false;
      // 加载最近构建分支（下拉“最近使用”分组，按时间降序取5个）
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

    // 加载服务列表（后端部分构建选择；默认全部开启；上次为部分构建时恢复勾选）
    _loadBuildServices(row) {
      const pref = this._buildPrefLoad(row.id);
      ajax('GET', '/api/cicd/builds/services?project_id=' + row.project_id, null, (r) => {
        this.servicesLoaded = true;
        if (r.code === 200) {
          this.serviceOptions = r.data || [];
          const toggles = {};
          if (pref && Array.isArray(pref.services) && pref.services.length) {
            // 恢复上次勾选的服务；新增服务不在上次列表，默认不勾选
            this.serviceOptions.forEach(s => { toggles[s] = pref.services.includes(s); });
            // 上次列表与现服务无交集（异常数据）时回退全部勾选
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
      }
    },
    // 全部勾选/取消全部：一键开关所有服务
    toggleAllServices(val) {
      this.serviceOptions.forEach(s => { this.serviceToggles[s] = !!val; });
    },
    // 弹窗内类型切换：重开构建弹窗（重拉分支/服务）
    onDeployTypeChange() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      this.buildViewType = this.buildType;
      this.openBuildDialog(this.buildEnv, this.buildType);
    },
    // 点击输入框：清空默认分支提示，开始输入即过滤
    onBranchFocus() {
      this.branchSearch = '';
    },
    // 输入框回车：直接采用输入值作为分支
    applyBranchInput() {
      const v = (this.branchSearch || '').trim();
      if (v) this.buildBranch = v;
    },
    // 该分支是否为最近构建选择过的分支
    isRecentBranch(b) {
      return this.recentBranches.includes(b);
    },
    // 树形过滤
    filterBranchTree(value, data) {
      if (!value) return true;
      if (data.isBranch) return data.branch.toLowerCase().includes(value.toLowerCase());
      return (data.children || []).some(c => this.filterBranchTree(value, c));
    },
    // 树形选择分支：叶子设置 buildBranch；目录节点自动展开/收起
    onBranchNodeClick(data) {
      if (data && data.isBranch) this.buildBranch = data.branch;
    },
    executeBuild() {
      if (!this.buildBranch.trim()) {
        ElementPlus.ElMessage.warning('请选择或输入分支');
        return;
      }
      // 构建范围：始终以开启的服务为准（去掉「全部服务」开关后，服务列表常显、逐个开关控制）
      let services = [];
      if (this.serviceOptions.length > 1) {
        services = this.serviceOptions.filter(s => this.serviceToggles[s]);
        if (!services.length) {
          ElementPlus.ElMessage.warning('请至少开启一个要构建的服务');
          return;
        }
      }
      this.buildTriggering = true;
      const env = this.buildEnv;
      // 保存本次构建配置，下次打开弹框自动恢复
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
          this.openProgressDrawer(res.data);
        } else {
          ElementPlus.ElMessage.error(res.message || '触发失败');
        }
      }, () => { this.buildTriggering = false; });
    },
    // ─── 构建进度抽屉 ─────────────────────────────
    openProgressDrawer(build) {
      this.bpBuild = build;
      this.bpSteps = [];
      this.bpLogFull = '';
      this.bpLogByStep = {};
      this.bpLogMode = 'all';
      this.bpDrawerVisible = true;
      // 启动实时计时器（每 100ms 更新 bpNow 触发步骤耗时重算）
      this.stopBpTimer();
      this.bpNow = Date.now();
      this.bpTimer = setInterval(() => { this.bpNow = Date.now(); }, 100);
      this.connectBuildSteps();
    },
    // SSE 订阅步骤变化（Agent 回调 → Master 推送，无需轮询）
    connectBuildSteps() {
      this.disconnectBpSteps();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/steps/stream?token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpStepES = es;
      es.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        this.bpSteps = data.steps || [];
        // 始终只维持 1 条 all 模式 SSE；切换步骤只改本地视图，不重连
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
            // 仅当构建从运行中转为终态时刷新环境表格（历史构建查看不触发）
            if (prevStatus === 'running' || prevStatus === 'pending') {
              this.loadEnvs();
            }
          }
        }
      };
      es.onerror = () => {
        es.close();
        this.bpStepES = null;
        // 连接异常降级：拉取一次步骤快照兜底
        this.fetchBuildSteps();
      };
    },
    disconnectBpSteps() {
      if (this.bpStepES) { this.bpStepES.close(); this.bpStepES = null; }
    },
    // 一次性获取步骤快照（SSE 连接失败时兜底）
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
    // step_no → SSE 日志类型（git/mvn/product/build/push/deploy）
    bpStepType(stepNo) {
      return { 1: 'git', 2: 'mvn', 3: 'product', 4: 'build', 5: 'push', 6: 'deploy' }[stepNo] || 'git';
    },
    // 解析步骤时间字符串，兼容秒级与毫秒级（后端新格式带 .mmm）
    parseStepTime(str) {
      const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?/.exec(str || '');
      if (!m) return NaN;
      const ms = m[7] ? m[7].padEnd(3, '0') : '0';
      return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], +ms).getTime();
    },
    // 格式化秒数为 时:分:秒 / 分:秒 / 秒.十分之一
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
    // 步骤耗时：运行中实时计时（依赖 bpNow 500ms 刷新），终态显示后端 duration
    bpStepDuration(s) {
      if (s.status === 'running' && s.started_at) {
        const st = this.parseStepTime(s.started_at);
        if (!isNaN(st)) {
          return this.fmtDuration((this.bpNow - st) / 1000);
        }
      }
      if (s.duration) {
        return this.fmtDuration(s.duration);
      }
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
    // 点击步骤圈：只看该步骤日志（本地切分，不重连）
    switchBpLog(stepNo) {
      this.bpLogMode = this.bpStepType(stepNo);
    },
    // 总览模式（本地切分，不重连）
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
    // 从指定步骤重跑：复用原节点已完成步骤的产物，不重新 clone
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
            // 用后端返回的真实状态刷新（重跑进入调度队列，可能为 pending 等待派发）
            this.bpBuild = Object.assign({}, this.bpBuild, res.data || {}, { error_msg: '' });
            this.bpLogFull = '';
            this.bpLogByStep = {};
            // 重新拉取步骤 SSE 获取真实状态（首帧即重置后的快照）
            this.connectBuildSteps();
            this.connectBuildLog('all');
          } else {
            ElementPlus.ElMessage.error(res.msg || '重跑失败');
          }
        });
      }).catch(() => {});
    },
    viewBuildLog(build) {
      this.detailVisible = false;
      this.openProgressDrawer(build);
    },
    loadEnvBuilds(envId) {
      ajax('GET', '/api/cicd/builds?environment_id=' + envId + '&project_type=' + (this.detailBuildType || 'backend'), null, (res) => {
        this.envBuilds = (res.code === 200) ? (res.data || []) : [];
      });
    },
    bpStatusType(status) {
      const map = { success: 'success', failed: 'danger', running: 'warning', pending: 'info', cancelled: 'info' };
      return map[status] || 'info';
    },
    bpStatusText(status) {
      const map = { success: '成功', failed: '失败', running: '运行中', pending: '等待中', cancelled: '已取消' };
      return map[status] || status || '';
    },
    bpStepStatus(step) {
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
          // 抽屉状态由步骤 SSE 自动更新；刷新环境表格同步状态
          this.loadEnvs();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      }, () => { this.selectDirsSaving = false; });
    },
    onDetailTabChange(tab) {
      if (tab === 'builds_frontend' || tab === 'builds_backend') {
        this.detailBuildType = (tab === 'builds_frontend') ? 'frontend' : 'backend';
        if (this._detailEnvId) this.loadEnvBuilds(this._detailEnvId);
      }
    }
  },
  beforeUnmount() {
    if (this.progressEventSource) { this.progressEventSource.close(); this.progressEventSource = null; }
    if (this.syncEventSource) { this.syncEventSource.close(); this.syncEventSource = null; }
    this.stopBpPolling();
  },
  created() {
    // 无回收站操作权限时强制停留在“运行中”标签页
    if (!this.$auth.hasPermission('op:recycle_admin')) {
      this.showDeleted = false;
    }
    this.loadProjects();
    this.loadEnvs();
  }
};


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
            <el-tag v-if="scope.row.last_build" :type="buildStatusType(scope.row.last_build.status)" size="small"
                    style="cursor:pointer" @click="openProgressDrawer(scope.row.last_build)">
              [[ buildStatusText(scope.row.last_build.status) ]]
            </el-tag>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="最后分支" width="120">
          <template #default="scope">
            <span v-if="scope.row.last_build" style="font-size:12px;font-family:monospace">[[ scope.row.last_build.branch ]]</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="执行人" width="90" align="center">
          <template #default="scope">
            <span v-if="scope.row.last_build" style="font-size:12px">[[ scope.row.last_build.triggered_by ]]</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showDeleted" label="构建时间" width="150">
          <template #default="scope">
            <span v-if="scope.row.last_build" style="font-size:12px;color:#909399">[[ scope.row.last_build.created_at ]]</span>
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
              <el-button v-if="$auth.hasPermission('op:cicd_build')" type="warning" size="small" link @click="openBuildDialog(scope.row)">构建</el-button>
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

    <!-- 构建弹窗 -->
    <el-dialog v-model="buildDialogVisible" :title="'构建 - ' + (buildEnv?.project || '') + '-' + (buildEnv?.environment || '')" width="480px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="分支">
          <el-select v-model="buildBranch" filterable allow-create default-first-option
                     :filter-method="filterBranches" @visible-change="onBranchDrop"
                     :loading="branchLoading" loading-text="加载分支中..."
                     placeholder="选择或输入分支" style="width:100%">
            <el-option-group v-if="recentBranchesFiltered.length" label="最近使用">
              <el-option v-for="b in recentBranchesFiltered" :key="'recent-' + b" :label="b" :value="b" />
            </el-option-group>
            <el-option-group label="全部分支">
              <el-option v-for="b in branchFiltered" :key="b" :label="b" :value="b" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item v-if="serviceOptions.length > 1" label="构建范围">
          <el-switch v-model="buildAllServices" active-text="全部服务" inline-prompt style="margin-bottom:8px" />
          <template v-if="!buildAllServices">
            <div style="display:flex;flex-direction:column;gap:8px;width:100%">
              <div v-for="s in serviceOptions" :key="s" style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border:1px solid #e4e7ed;border-radius:4px">
                <span style="font-family:monospace;font-size:13px">[[ s ]]</span>
                <el-switch v-model="serviceToggles[s]" />
              </div>
            </div>
            <div style="color:#909399;font-size:12px;margin-top:4px">仅对开启的服务执行产物收集 / Docker Build / Push，未开启的服务自动跳过</div>
          </template>
        </el-form-item>
      </el-form>
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
          <el-button v-if="bpBuild && (bpBuild.status === 'running' || bpBuild.status === 'pending')"
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
      <div ref="bpLogContainer" class="bp-log-box">[[ bpLog || '等待日志输出...' ]]</div>
    </el-drawer>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" :title="detailEnv + ' 详细信息'" width="800px" top="5vh">
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

          <el-tab-pane label="构建记录" name="builds">
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
            <el-empty v-else description="暂无构建记录" :image-size="60" />
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
  `,
  data() {
    return {
      envs: [],
      projects: [],
      selectedProject: '',
      loading: false,
      importing: false,
      detailVisible: false,
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
      buildEnv: null,
      buildBranch: '',
      branchOptions: [],
      branchFiltered: [],
      branchLoading: false,
      recentBranches: [],
      recentBranchesFiltered: [],
      buildAllServices: true,
      serviceToggles: {},
      serviceOptions: [],
      buildTriggering: false,
      // 构建进度抽屉
      bpDrawerVisible: false,
      bpBuild: null,
      bpSteps: [],
      bpLog: '',
      bpLogMode: 'all',
      bpStepES: null,
      bpES: null,
      // 步骤实时计时（500ms 刷新一次，展示当前步骤运行时长）
      bpNow: Date.now(),
      bpTimer: null,
      // 构建记录
      envBuilds: []
    };
  },
  computed: {
    sortedEnvs() {
      var list = this.envs.slice();
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
          all_services: this.buildAllServices,
          services: enabled
        }));
      } catch (e) { /* 忽略存储异常（隐私模式等） */ }
    },
    openBuildDialog(row) {
      this.buildEnv = row;
      // 恢复上次构建配置（localStorage 按环境记忆：分支/全部或部分/勾选服务），无记录时回退到最后一次构建分支
      const pref = this._buildPrefLoad(row.id);
      const lastBranch = (row.last_build && row.last_build.branch) || '';
      this.buildBranch = (pref && pref.branch) || lastBranch || 'master';
      this.branchOptions = [];
      this.branchFiltered = [];
      this.recentBranches = [];
      this.recentBranchesFiltered = [];
      this.buildAllServices = pref ? !!pref.all_services : true;
      this.serviceToggles = {};
      this.serviceOptions = [];
      this.buildDialogVisible = true;
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
      // 加载服务列表（用于部分构建选择，默认全部开启；上次为部分构建时恢复勾选）
      if (row.project_id) {
        ajax('GET', '/api/cicd/builds/services?project_id=' + row.project_id, null, (r) => {
          if (r.code === 200) {
            this.serviceOptions = r.data || [];
            const toggles = {};
            this.serviceOptions.forEach(s => { toggles[s] = true; });
            if (!this.buildAllServices && pref && Array.isArray(pref.services)) {
              // 部分构建：恢复上次勾选的服务，新增服务默认不勾选
              this.serviceOptions.forEach(s => { toggles[s] = pref.services.includes(s); });
            }
            this.serviceToggles = toggles;
          }
        });
      }
      // 加载远程分支列表
      if (row.project_id) {
        this.branchLoading = true;
        ajax('GET', '/api/cicd/builds/branches?project_id=' + row.project_id, null, (r) => {
          this.branchLoading = false;
          if (r.code === 200) {
            let branches = r.data || [];
            // 最近使用的分支置顶（优先展示，确保下拉第一项即为上次分支）
            if (lastBranch) {
              branches = branches.filter(b => b !== lastBranch);
              branches.unshift(lastBranch);
            }
            this.branchOptions = branches;
            this.branchFiltered = this.branchOptions;
          } else {
            ElementPlus.ElMessage.warning(r.message || '该项目暂未配置模板');
          }
        }, () => { this.branchLoading = false; });
      }
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
    executeBuild() {
      if (!this.buildBranch.trim()) {
        ElementPlus.ElMessage.warning('请选择或输入分支');
        return;
      }
      // 部分构建模式：收集开启的服务
      let services = [];
      if (!this.buildAllServices && this.serviceOptions.length > 1) {
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
        services: services
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
      this.bpLog = '';
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
        // 总览模式：后端 type=all 自动拼接全部步骤日志，只需确保 SSE 已连接
        if (this.bpLogMode === 'all' && !this.bpES) {
          this.connectBuildLog('all');
        }
        const buildStatus = data.build_status;
        if (buildStatus) {
          const prevStatus = this.bpBuild.status;
          this.bpBuild = Object.assign({}, this.bpBuild, { status: buildStatus });
          if (['success', 'failed', 'cancelled'].includes(buildStatus)) {
            // 构建结束：关闭步骤 SSE，保留日志流继续传输（避免初始数据被截断）
            this.disconnectBpSteps();
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
      this.disconnectBpLog();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/log?type=' + type + '&follow=true&token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpES = es;
      es.onmessage = (evt) => {
        this.bpLog += evt.data.replace(/\\n/g, '\n');
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
    // 点击步骤圈：只看该步骤日志
    switchBpLog(stepNo) {
      this.bpLogMode = this.bpStepType(stepNo);
      this.bpLog = '';
      this.connectBuildLog(this.bpLogMode);
    },
    // 总览模式：后端 type=all 自动拼接全部步骤日志
    switchBpLogAll() {
      this.bpLogMode = 'all';
      this.bpLog = '';
      this.connectBuildLog('all');
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
            this.bpLog = '';
            // 重新拉取步骤 SSE 获取真实状态（首帧即重置后的快照）
            this.connectBuildSteps();
            this.connectBuildLog(this.bpLogMode);
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
      ajax('GET', '/api/cicd/builds?environment_id=' + envId, null, (res) => {
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
      if (step.status === 'running') return 'process';
      if (step.status === 'failed') return 'error';
      return 'wait';
    },
    onDetailTabChange(tab) {
      if (tab === 'builds' && this._detailEnvId) {
        this.loadEnvBuilds(this._detailEnvId);
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


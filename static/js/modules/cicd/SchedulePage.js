const SchedulePage = {
  name: 'SchedulePage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="card schedule-page">
  <div class="page-header">
    <div class="section-title">调度中心</div>
    <div style="display:flex;align-items:center;gap:12px">
      <span style="font-size:12px;color:#909399">
        在线 [[ onlineCount ]] / [[ agents.length ]] · 排队 [[ queue.length ]] · 运行中 [[ running.length ]]
      </span>
      <el-tag :type="streamOk ? 'success' : 'info'" size="small" effect="plain">
        [[ streamOk ? '实时连接中' : '连接已断开' ]]
      </el-tag>
      <el-button v-if="agentOpAllowed" size="small" type="primary" @click="openAgentDialog">+ 添加 Agent</el-button>
      <el-button size="small" @click="loadOverview">刷新</el-button>
    </div>
  </div>

  <div class="schedule-body">
    <!-- 左侧：构建节点 -->
    <div class="schedule-left">
      <div class="section-title" style="margin-bottom:10px">构建节点</div>
      <div v-if="agents.length === 0" style="color:#909399;padding:20px 0;text-align:center">暂无 Agent</div>
      <div class="agent-list">
        <el-card v-for="a in agents" :key="a.id" class="agent-card" :class="{'agent-disabled': a.disabled, 'agent-offline': !a.disabled && (a.state === 'stopped' || a.state === 'server_offline')}" shadow="hover" style="cursor:pointer" @click="openDetail(a)">
          <div class="agent-head">
            <span class="agent-name">[[ a.name ]] ([[ a.host ]]:[[ a.port ]])</span>
            <div style="display:flex;align-items:center;gap:6px">
              <el-tag :type="stateType(a.state)" size="small">[[ stateLabel(a.state) ]]</el-tag>
              <el-switch :model-value="!a.disabled" size="small" inline-prompt
                         active-text="启用" inactive-text="禁用"
                         @click.stop @change="toggleDisable(a)" />
            </div>
          </div>
          <div class="agent-meta">
            配置 [[ a.cpu_cores || '-' ]] 核 · [[ a.mem_total_gb || '-' ]] GB 内存 · [[ a.disk_total_gb || '-' ]] GB 磁盘 · 任务 [[ a.current_load ]]/[[ a.max_concurrent ]]
            <span v-if="(a.state === 'idle' || a.state === 'running') && !a.docker_ok" style="color:#f56c6c"> · Docker 异常</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">CPU</span>
            <el-progress :percentage="clamp(a.cpu_load)" :stroke-width="10" :color="metricColor(a.cpu_load)" />
          </div>
          <div class="metric-row">
            <span class="metric-label">内存</span>
            <el-progress :percentage="clamp(a.mem_percent)" :stroke-width="10" :color="metricColor(a.mem_percent)" />
          </div>
          <div class="metric-row">
            <span class="metric-label">磁盘</span>
            <el-tooltip :content="'已使用 ' + (a.disk_used_gb || 0) + ' GB / 剩余 ' + ((a.disk_total_gb || 0) - (a.disk_used_gb || 0)).toFixed(1) + ' GB'" placement="top">
              <el-progress :percentage="clamp(a.disk_percent)" :stroke-width="10" :color="metricColor(a.disk_percent)" />
            </el-tooltip>
          </div>
          <div class="metric-row">
            <span class="metric-label">磁盘IO</span>
            <span class="metric-val">↓[[ a.disk_read_kb ]] KB/s&nbsp;&nbsp;↑[[ a.disk_write_kb ]] KB/s</span>
          </div>
          <div class="metric-row">
            <span class="metric-label">网络</span>
            <span class="metric-val">↓[[ a.net_rx_kb ]] KB/s&nbsp;&nbsp;↑[[ a.net_tx_kb ]] KB/s</span>
          </div>
          <div class="metric-row" style="justify-content:space-between">
            <span class="metric-label" style="width:auto; white-space:nowrap">Docker 缓存</span>
            <span class="cache-size" :style="{ color: cacheColor(a.docker_cache_size), whiteSpace: 'nowrap', fontWeight: 'bold', flexShrink: 0 }">[[ formatCache(a.docker_cache_size) ]]</span>
          </div>
          <div class="agent-meta" style="margin-top:6px;display:flex;justify-content:space-between;align-items:center">
            <span>心跳 [[ a.last_heartbeat || '-' ]]</span>
            <template v-if="a.state !== 'server_offline'">
              <div style="display:flex;gap:4px">
                <el-button v-if="agentOpAllowed" size="small" @click.stop="openEditAgent(a)">编辑</el-button>
                <el-button v-if="['idle','running','disabled'].includes(a.state) && agentOpAllowed" size="small" @click.stop="openUpdateDialog(a)">更新</el-button>
                <el-button v-if="agentOpAllowed" size="small" @click.stop="a.state === 'stopped' ? reinstallAgent(a) : openCleanupDialog(a, 'reset')">[[ a.state === 'stopped' ? '安装' : '重置' ]]</el-button>
                <el-button v-if="agentOpAllowed" size="small" @click.stop="openCleanupDialog(a, 'uninstall')">卸载</el-button>
              </div>
            </template>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 右侧：调度日志 -->
    <div class="schedule-right">
      <div class="section-title" style="margin-bottom:10px">调度日志</div>
      <el-table :data="scheduleLogs" stripe border size="small" row-key="id"
                :header-cell-style="{background:'#f5f7fa',fontWeight:'bold'}"
                @expand-change="onExpandChange">
        <el-table-column type="expand">
          <template #default="s">
            <div class="schedule-log-detail" v-loading="s.row._loading">
              <pre v-if="s.row._logs">[[ s.row._logs ]]</pre>
              <span v-else style="color:#909399">加载中...</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="build_no" label="构建编号" width="170" />
        <el-table-column prop="project_name" label="项目" min-width="110" />
        <el-table-column prop="environment_name" label="环境" min-width="100" show-overflow-tooltip />
        <el-table-column prop="branch" label="分支" width="110" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="s">
            <el-tag :type="logStatusType(s.row.status)" size="small">[[ logStatusLabel(s.row.status) ]]</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="selected_agent" label="执行节点" width="110">
          <template #default="s">[[ s.row.selected_agent || '-' ]]</template>
        </el-table-column>
        <el-table-column prop="triggered_by" label="触发人" width="90" />
        <el-table-column prop="created_at" label="时间" width="155" />
      </el-table>
    </div>
  </div>

  <!-- ═══ Agent 详情弹窗（左右分栏） ═══ -->
  <el-drawer v-model="detailVisible" :title="detailAgent ? detailAgent.name + ' · 详情' : ''" size="80%" @closed="closeDetail">
    <div v-if="detailAgent" class="detail-split">
      <!-- 左侧：系统信息 + 折线图 -->
      <div class="detail-left">
        <el-card shadow="never" class="detail-sysinfo">
          <template #header><span style="font-weight:bold">系统信息</span></template>
          <div class="sysinfo-grid">
            <div class="sysinfo-item"><span class="si-label">操作系统</span><span class="si-val">[[ sysInfo.os_name || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">内核</span><span class="si-val">[[ sysInfo.kernel || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">架构</span><span class="si-val">[[ sysInfo.arch || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">主机名</span><span class="si-val">[[ sysInfo.hostname || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">CPU 型号</span><span class="si-val">[[ sysInfo.cpu_model || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">CPU 核数</span><span class="si-val">[[ detailAgent.cpu_cores ]] 逻辑 / [[ sysInfo.cpu_physical_cores || '-' ]] 物理</span></div>
            <div class="sysinfo-item"><span class="si-label">内存</span><span class="si-val">[[ detailAgent.mem_total_gb ]] GB（已用 [[ detailAgent.mem_used_gb || 0 ]] GB / 可用 [[ detailAgent.mem_avail_gb || 0 ]] GB）</span></div>
            <div class="sysinfo-item"><span class="si-label">Docker</span><span class="si-val">[[ sysInfo.docker_version || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">Docker 路径</span><span class="si-val">[[ sysInfo.docker_path || '-' ]]</span></div>
            <div class="sysinfo-item"><span class="si-label">工作目录</span><span class="si-val">[[ detailAgent.work_dir || '/data/cicd' ]]</span></div>
          </div>
        </el-card>
        <div class="detail-charts">
          <div class="chart-wrap">
            <div ref="chartCpu" class="chart-box"></div>
            <div class="chart-latest"><span style="color:#409eff">[[ latestMetrics.cpu_load !== undefined ? latestMetrics.cpu_load + '%' : '-' ]]</span></div>
          </div>
          <div class="chart-wrap">
            <div ref="chartMem" class="chart-box"></div>
            <div class="chart-latest"><span style="color:#67c23a">[[ latestMetrics.mem_percent !== undefined ? latestMetrics.mem_percent + '%' : '-' ]]</span></div>
          </div>
          <div class="chart-wrap">
            <div ref="chartDisk" class="chart-box"></div>
            <div class="chart-latest">
              <span style="color:#409eff">读 [[ latestMetrics.disk_read_kb || 0 ]]KB/s</span>
              <span style="color:#e6a23c">写 [[ latestMetrics.disk_write_kb || 0 ]]KB/s</span>
            </div>
          </div>
          <div class="chart-wrap">
            <div ref="chartNet" class="chart-box"></div>
            <div class="chart-latest">
              <span style="color:#409eff">收 [[ latestMetrics.net_rx_kb || 0 ]]KB/s</span>
              <span style="color:#e6a23c">发 [[ latestMetrics.net_tx_kb || 0 ]]KB/s</span>
            </div>
          </div>
          <div class="chart-wrap">
            <div ref="chartLoad" class="chart-box"></div>
            <div class="chart-latest">
              <span style="color:#409eff">1m [[ latestMetrics.load1 || 0 ]]</span>
              <span style="color:#67c23a">5m [[ latestMetrics.load5 || 0 ]]</span>
              <span style="color:#e6a23c">15m [[ latestMetrics.load15 || 0 ]]</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 右侧：Agent 日志 -->
      <div class="detail-right">
        <div style="font-weight:bold;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between">
          <span>Agent 日志</span>
          <el-button size="small" @click="clearDetailLog">清空显示</el-button>
        </div>
        <div class="agent-log-box" ref="detailLogContainer">
          <pre>[[ detailLog ]]</pre>
        </div>
      </div>
    </div>
  </el-drawer>

  <!-- ═══ 添加/重新安装 Agent 弹窗 ═══ -->
  <el-dialog v-model="showAgentDialog" :title="reinstallMode ? '重新安装 Agent' : '添加 Agent（远程安装）'" width="520px" :close-on-click-modal="false">
    <el-form label-width="100px" size="small">
      <el-form-item label="名称" required><el-input v-model="agentForm.name" placeholder="build-node-01" :disabled="reinstallMode" /></el-form-item>
      <el-form-item label="主机地址" required><el-input v-model="agentForm.host" placeholder="192.168.1.100" :disabled="reinstallMode" /></el-form-item>
      <el-form-item label="SSH 端口"><el-input-number v-model="agentForm.ssh_port" :min="1" :max="65535" :disabled="reinstallMode" /></el-form-item>
      <el-form-item label="认证方式" required>
        <el-radio-group v-model="agentForm.auth_type">
          <el-radio label="credential">凭据</el-radio>
          <el-radio label="password">账号密码</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="agentForm.auth_type==='credential'" label="选择凭据" required>
        <el-select v-model="agentForm.credential_id" placeholder="选择已有凭据" style="width:100%">
          <el-option v-for="c in credentials" :key="c.id" :label="c.name + ' (' + c.type + ')'" :value="c.id" />
        </el-select>
      </el-form-item>
      <template v-if="agentForm.auth_type==='password'">
        <el-form-item label="用户名" required><el-input v-model="agentForm.ssh_username" placeholder="root" /></el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="agentForm.ssh_password" type="password" show-password :placeholder="reinstallMode?'留空则使用已保存凭据':'请输入 SSH 密码'" />
        </el-form-item>
      </template>
      <el-form-item label="Master 地址"><el-input v-model="agentForm.master_url" :placeholder="masterUrlPlaceholder" /></el-form-item>
      <el-form-item label="工作目录"><el-input v-model="agentForm.work_dir" placeholder="/data/cicd" :disabled="reinstallMode" /></el-form-item>
      <el-divider content-position="left">NFS 挂载（安装时自动挂载，无需登录服务器）</el-divider>
      <el-form-item label="挂载目录">
        <el-input v-model="agentForm.frontend_mount_dir" placeholder="/web（Agent 机 NFS 挂载根；发布目标 = 挂载根/项目/环境/web，如 /web/ysh/test/web）" />
        <div style="color:#909399;font-size:12px;margin-top:2px">末尾 / 可不填，保存时自动去除</div>
      </el-form-item>
      <el-form-item label="NFS 服务器">
        <el-input v-model="agentForm.nfs_server" placeholder="192.168.1.200" />
      </el-form-item>
      <el-form-item label="NFS 共享目录">
        <el-input v-model="agentForm.nfs_share" placeholder="/data/project" />
        <div style="color:#909399;font-size:12px;margin-top:4px">安装时自动挂载 [[ agentForm.nfs_server || 'NFS服务器' ]]:[[ agentForm.nfs_share || '共享目录' ]] → [[ agentForm.frontend_mount_dir || '/web' ]] 并写入 /etc/fstab</div>
        <div style="color:#e6a23c;font-size:12px;margin-top:2px">⚠ 挂载目录不要填写 /etc 等系统目录；目录不存在会自动递归创建</div>
        <div style="color:#909399;font-size:12px;margin-top:2px">末尾 / 可不填，自动去除</div>
      </el-form-item>
      <el-form-item label="保留构建数">
        <el-input-number v-model="agentForm.keep_builds" :min="1" :max="50" />
        <span style="color:#909399;margin-left:8px;font-size:12px">每环境保留的最近构建数，超出自动清理</span>
      </el-form-item>
      <el-form-item label="安装 Docker"><el-switch v-model="agentForm.install_docker" /></el-form-item>
      <el-divider content-position="left">Harbor 镜像仓库</el-divider>
      <el-form-item label="仓库类型" required>
        <el-radio-group v-model="agentForm.harbor_type">
          <el-radio label="public">公有</el-radio>
          <el-radio label="private">私有</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="Harbor 地址" required><el-input v-model="agentForm.harbor_url" placeholder="hub.example.com" /></el-form-item>
      <el-form-item v-if="agentForm.harbor_type==='private'" label="IP 映射" required>
        <el-input v-model="agentForm.harbor_ip" placeholder="192.168.1.200" />
        <div style="color:#909399;font-size:12px;margin-top:4px">安装时将在远程 /etc/hosts 写入：[[ agentForm.harbor_ip || '<IP>' ]] [[ agentForm.harbor_url || '<域名>' ]]</div>
      </el-form-item>
      <el-form-item label="Harbor 凭据" required>
        <el-select v-model="agentForm.harbor_credential_id" placeholder="选择账号密码凭据" style="width:100%">
          <el-option v-for="c in harborCredentials" :key="c.id" :label="c.name + (c.username ? ' (' + c.username + ')' : '')" :value="c.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showAgentDialog=false">取消</el-button>
      <el-button v-if="agentOpAllowed" type="primary" :loading="saving" @click="addAgent">开始安装</el-button>
    </template>
  </el-dialog>

  <!-- ═══ 编辑 Agent 配置弹窗（仅改 DB 配置，不触发重装；SSH/Harbor 变更下次安装生效） ═══ -->
  <el-dialog v-model="editAgentVisible" title="编辑 Agent 配置" width="560px" :close-on-click-modal="false">
    <el-form label-width="110px" size="small">
      <el-form-item label="名称" required><el-input v-model="editForm.name" placeholder="build-node-01" /></el-form-item>
      <el-form-item label="主机地址" required><el-input v-model="editForm.host" placeholder="192.168.1.100" /></el-form-item>
      <el-form-item label="SSH 端口"><el-input-number v-model="editForm.ssh_port" :min="1" :max="65535" /></el-form-item>
      <el-form-item label="认证方式" required>
        <el-radio-group v-model="editForm.auth_type">
          <el-radio label="credential">凭据</el-radio>
          <el-radio label="password">账号密码</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="editForm.auth_type==='credential'" label="选择凭据">
        <el-select v-model="editForm.credential_id" placeholder="选择已有凭据" style="width:100%">
          <el-option v-for="c in credentials" :key="c.id" :label="c.name + ' (' + c.type + ')'" :value="c.id" />
        </el-select>
      </el-form-item>
      <template v-if="editForm.auth_type==='password'">
        <el-form-item label="用户名" required><el-input v-model="editForm.ssh_username" placeholder="root" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="editForm.ssh_password" type="password" show-password placeholder="留空则保持已保存的密码" />
        </el-form-item>
      </template>
      <el-form-item label="Master 地址"><el-input v-model="editForm.master_url" :placeholder="masterUrlPlaceholder" /></el-form-item>
      <el-form-item label="工作目录"><el-input v-model="editForm.work_dir" placeholder="/data/cicd" /></el-form-item>
      <el-divider content-position="left">NFS 挂载</el-divider>
      <el-form-item label="挂载目录">
        <el-input v-model="editForm.frontend_mount_dir" placeholder="/web（Agent 机 NFS 挂载根；发布目标 = 挂载根/项目/环境/web）" />
      </el-form-item>
      <el-form-item label="NFS 服务器"><el-input v-model="editForm.nfs_server" placeholder="192.168.1.200" /></el-form-item>
      <el-form-item label="NFS 共享目录">
        <el-input v-model="editForm.nfs_share" placeholder="/data/project" />
        <div style="color:#e6a23c;font-size:12px;margin-top:2px">⚠ 挂载目录不要填写 /etc 等系统目录；目录不存在会自动递归创建</div>
        <div style="color:#909399;font-size:12px;margin-top:2px">末尾 / 可不填，自动去除</div>
      </el-form-item>
      <el-form-item label="保留构建数">
        <el-input-number v-model="editForm.keep_builds" :min="1" :max="50" />
        <span style="color:#909399;margin-left:8px;font-size:12px">每环境保留的最近构建数，超出自动清理</span>
      </el-form-item>
      <el-form-item label="禁用调度"><el-switch v-model="editForm.disabled" /></el-form-item>
      <el-divider content-position="left">Harbor 镜像仓库</el-divider>
      <el-form-item label="仓库类型" required>
        <el-radio-group v-model="editForm.harbor_type">
          <el-radio label="public">公有</el-radio>
          <el-radio label="private">私有</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="Harbor 地址"><el-input v-model="editForm.harbor_url" placeholder="hub.example.com" /></el-form-item>
      <el-form-item v-if="editForm.harbor_type==='private'" label="IP 映射">
        <el-input v-model="editForm.harbor_ip" placeholder="192.168.1.200" />
        <div style="color:#909399;font-size:12px;margin-top:4px">安装时将在远程 /etc/hosts 写入：[[ editForm.harbor_ip || '<IP>' ]] [[ editForm.harbor_url || '<域名>' ]]</div>
      </el-form-item>
      <el-form-item label="Harbor 凭据">
        <el-select v-model="editForm.harbor_credential_id" placeholder="选择账号密码凭据" style="width:100%">
          <el-option v-for="c in harborCredentials" :key="c.id" :label="c.name + (c.username ? ' (' + c.username + ')' : '')" :value="c.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editAgentVisible=false">取消</el-button>
      <el-button v-if="agentOpAllowed" type="primary" :loading="savingEdit" @click="saveEditAgent">保存</el-button>
    </template>
  </el-dialog>

  <!-- ═══ Agent 安装进度弹窗 ═══ -->
  <el-dialog v-model="installVisible" :title="installTitle" width="30%" :close-on-click-modal="installDone" :close-on-press-escape="installDone" top="12vh">
    <div style="margin-bottom:12px">
      <el-steps :active="installStep" finish-status="success" align-center size="small">
        <el-step v-for="(t, i) in installStepTitles" :key="i" :title="t" />
      </el-steps>
    </div>
    <div class="cicd-log-viewer" style="height:44vh;font-size:12px">
      <div v-for="(line, i) in installLogs" :key="i" class="log-line" :style="{color: line.color || '#d4d4d4'}">[[ line.text ]]</div>
    </div>
    <template #footer>
      <el-button v-if="installDone" type="primary" @click="installVisible=false">完成</el-button>
    </template>
  </el-dialog>

  <!-- ═══ 卸载/重置弹窗 ═══ -->
  <el-dialog v-model="cleanupVisible" :title="(cleanupMode==='uninstall'?'卸载':'重置') + ' Agent「' + (cleanupAgent?cleanupAgent.name:'') + '」'" width="440px" :close-on-click-modal="false">
    <el-alert v-if="cleanupMode==='uninstall'" type="error" :closable="false" show-icon style="margin-bottom:14px">
      <template #title>卸载将执行以下操作（不可恢复）</template>
      <template #default>
        <div style="line-height:1.8">1. 停止并移除 cicd-agent 服务<br>2. 删除远程二进制 /usr/local/bin/cicd-agent<br>3. 删除工作目录 [[ cleanupAgent?cleanupAgent.work_dir:'/data/cicd' ]]<br>4. [[ cleanupAgent && cleanupAgent.frontend_mount_dir ? '卸载 NFS 挂载 ' + cleanupAgent.frontend_mount_dir : '删除本地数据库记录' ]]</div>
      </template>
    </el-alert>
    <el-alert v-else type="warning" :closable="false" show-icon style="margin-bottom:14px">
      <template #title>重置将执行以下操作（保留本地记录，可重新安装）</template>
      <template #default>
        <div style="line-height:1.8">1. 停止并移除 cicd-agent 服务<br>2. 删除远程二进制 /usr/local/bin/cicd-agent<br>3. 删除工作目录 [[ cleanupAgent?cleanupAgent.work_dir:'/data/cicd' ]]<br>4. [[ cleanupAgent && cleanupAgent.frontend_mount_dir ? '（可选）卸载 NFS 挂载 ' + cleanupAgent.frontend_mount_dir : '' ]]</div>
      </template>
    </el-alert>
    <el-form label-width="100px" size="small">
      <el-form-item label="主机"><span style="font-weight:bold">[[ cleanupAgent?cleanupAgent.host:'' ]]</span></el-form-item>
      <el-form-item label="卸载 Docker">
        <el-switch v-model="cleanupForm.remove_docker" />
        <span style="margin-left:8px;color:#909399;font-size:12px">同时卸载 Docker</span>
      </el-form-item>
      <el-alert v-if="cleanupForm.remove_docker" type="warning" :closable="false" show-icon style="margin:-4px 0 12px 100px">
        <template #default>将停止并卸载 Docker，删除 /data/docker 与 /etc/docker</template>
      </el-alert>
      <el-form-item label="卸载 NFS">
        <el-switch v-model="cleanupForm.remove_nfs" :disabled="!(cleanupAgent && cleanupAgent.frontend_mount_dir)" />
        <span style="margin-left:8px;color:#909399;font-size:12px">[[ cleanupAgent && cleanupAgent.frontend_mount_dir ? '卸载 ' + cleanupAgent.frontend_mount_dir : '未配置 NFS 挂载' ]]</span>
      </el-form-item>
      <el-alert v-if="cleanupForm.remove_nfs && cleanupAgent && cleanupAgent.frontend_mount_dir" type="warning" :closable="false" show-icon style="margin:-4px 0 12px 100px">
        <template #default>将卸载 [[ cleanupAgent.frontend_mount_dir ]] 并清除 /etc/fstab 中的对应记录</template>
      </el-alert>
    </el-form>
    <template #footer>
      <el-button @click="cleanupVisible=false">取消</el-button>
      <el-button v-if="agentOpAllowed" :type="cleanupMode==='uninstall'?'danger':'warning'" :loading="saving" @click="confirmCleanup">确认[[ cleanupMode==='uninstall'?'卸载':'重置' ]]</el-button>
    </template>
  </el-dialog>

  <!-- ═══ 更新弹窗 ═══ -->
  <el-dialog v-model="updateVisible" :title="'更新 Agent「' + (updateTarget?updateTarget.name:'') + '」'" width="440px" :close-on-click-modal="false">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:14px">
      <template #title>更新将执行以下操作（不影响 Docker / 配置 / 工作目录）</template>
      <template #default>
        <div style="line-height:1.8">1. 上传新版二进制到 /usr/local/bin/cicd-agent<br>2. 重启 cicd-agent 服务（更新期间节点短暂离线）</div>
      </template>
    </el-alert>
    <el-form label-width="100px" size="small">
      <el-form-item label="主机"><span style="font-weight:bold">[[ updateTarget?updateTarget.host:'' ]]</span></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="updateVisible=false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="confirmUpdate">确认更新</el-button>
    </template>
  </el-dialog>
</div>
`,
  data() {
    return {
      agents: [], queue: [], running: [],
      scheduleLogs: [],
      streamOk: false,
      es: null,
      // 详情弹窗
      updateVisible: false,
      updateTarget: null,
      detailVisible: false,
      detailAgent: null,
      detailLog: '',
      detailLogEs: null,
      metricsEs: null,
      charts: {},
      latestMetrics: {},
      // 缓存管理
      // Agent 管理
      credentials: [],
      saving: false,
      showAgentDialog: false, reinstallMode: false, reinstallAgentId: null,
      editAgentVisible: false, savingEdit: false,
      editForm: {
        id: null, name: '', host: '', ssh_port: 22, auth_type: 'credential', credential_id: '',
        ssh_username: 'root', ssh_password: '', master_url: '', work_dir: '/data/cicd',
        frontend_mount_dir: '', nfs_server: '', nfs_share: '', keep_builds: 5, disabled: false,
        harbor_type: 'public', harbor_url: '', harbor_credential_id: '', harbor_ip: '',
      },
      agentForm: { name: '', host: '', ssh_port: 22, ssh_username: 'root', auth_type: 'credential', ssh_password: '', credential_id: '', master_url: '', work_dir: '/data/cicd', frontend_mount_dir: '', nfs_server: '', nfs_share: '', keep_builds: 5, install_docker: true, harbor_type: 'public', harbor_url: '', harbor_credential_id: '', harbor_ip: '' },
      installVisible: false, installStep: 0, installLogs: [], installDone: false, installSource: null, installAutoClose: null,
      installTitle: 'Agent 安装进度', installStepTitles: ['SSH 连接', '安装 Docker', '上传文件', '启动服务'],
      cleanupVisible: false, cleanupMode: 'uninstall', cleanupAgent: null,
      cleanupForm: { remove_docker: false, remove_nfs: false },
    };
  },
  computed: {
    // Agent 操作权限（op:agent）：无权限隐藏添加/更新/安装/重置/卸载等操作（后端仍 403 兜底）
    agentOpAllowed() {
      return !!(this.$auth && this.$auth.hasPermission('op:agent'));
    },
    onlineCount() { return this.agents.filter(a => a.state === 'idle' || a.state === 'running').length; },
    masterUrlPlaceholder() { return window.location.origin || 'http://192.168.1.x:8050'; },
    harborCredentials() { return this.credentials.filter(c => c.type === 'password'); },
    sysInfo() { return (this.detailAgent && this.detailAgent.sys_info) || {}; },
  },
  mounted() {
    this.connectStream();
    this.loadScheduleLogs();
    this.loadOverview(); // 首屏兜底：即使 SSE 异常，刷新页面也能先展示一次数据
  },
  activated() {
    // keep-alive 从其他标签切回时刷新日志（首次挂载 mounted 已加载，用标志避免重复调用）
    if (this._deactivated) {
      this._deactivated = false;
      this.loadScheduleLogs();
    }
    if (!this.es) this.connectStream();
  },
  deactivated() {
    this._deactivated = true;
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    if (this.es) { this.es.close(); this.es = null; }
    this.stopMetricsPolling();
  },
  beforeUnmount() {
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    if (this.es) { this.es.close(); this.es = null; }
    this.closeDetail();
    this.stopMetricsPolling();
  },
  methods: {
    // ─── 调度概览 ─────────────────────────────────────────
    loadOverview() {
      ajax('GET', '/api/cicd/schedule/overview', null, res => {
        if (res.code === 200) this.applyOverview(res.data);
      });
    },
    connectStream() {
      const token = localStorage.getItem('auth_token');
      const url = '/api/cicd/schedule/stream?token=' + encodeURIComponent(token || '');
      const es = new EventSource(url);
      this.es = es;
      es.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data && data.error) { this.streamOk = false; return; }
          if (data && data.agents) { this.applyOverview(data); this.streamOk = true; }
        } catch (e) { /* 忽略异常帧 */ }
      };
      es.onopen = () => { this.streamOk = true; };
      es.onerror = () => { this.streamOk = false; };
    },
    applyOverview(data) {
      this.agents = data.agents || [];
      this.queue = data.queue || [];
      this.running = data.running || [];
      // 如果详情弹窗打开，更新当前 agent 数据
      if (this.detailAgent) {
        const updated = this.agents.find(a => a.id === this.detailAgent.id);
        if (updated) this.detailAgent = { ...updated, sys_info: updated.sys_info || {} };
      }
    },
    loadScheduleLogs() {
      ajax('GET', '/api/cicd/schedule/logs', null, res => {
        if (res.code === 200) {
          this.scheduleLogs = (res.data || []).map(item => ({ ...item, _logs: null, _loading: false }));
        }
      });
    },
    onExpandChange(row, expandedRows) {
      if (!expandedRows.includes(row)) return;
      if (row._logs) return;
      row._loading = true;
      ajax('GET', '/api/cicd/schedule/logs/' + row.id, null, res => {
        row._loading = false;
        if (res.code === 200) row._logs = res.data.detail_logs || '无日志';
        else row._logs = '加载失败';
      });
    },

    // ─── 状态标签 ─────────────────────────────────────────
    logStatusType(s) {
      const m = { dispatched: 'success', dispatching: 'warning', no_agent: 'danger', same_env: 'warning', agent_full: 'warning', node_down: 'warning', failed: 'danger' };
      return m[s] || 'info';
    },
    logStatusLabel(s) {
      const m = { dispatched: '已调度', dispatching: '调度中', no_agent: '无节点', same_env: '同环境等待', agent_full: '等待Agent', node_down: '等待原节点', failed: '失败' };
      return m[s] || s;
    },
    stateType(state) {
      const m = { idle: 'success', running: 'warning', disabled: 'danger', offline: 'danger', stopped: 'warning', server_offline: 'info' };
      return m[state] || 'info';
    },
    stateLabel(state) {
      const m = { idle: '空闲', running: '运行中', disabled: '已禁用', offline: '离线', stopped: '服务停止', server_offline: '服务器离线' };
      return m[state] || state;
    },
    clamp(v) { return Math.min(Math.max(Math.round(v || 0), 0), 100); },
    metricColor(v) {
      if (v >= 85) return '#f56c6c';
      if (v >= 60) return '#e6a23c';
      return '#67c23a';
    },
    formatCache(size) {
      // 归一化显示：去掉数字与单位间的空格（如 "114.9 GB" -> "114.9GB"），避免空格处换行
      return String(size || '0B').trim().replace(/\s+/g, '');
    },
    cacheColor(size) {
      // Docker 缓存大小 → 颜色：<1G深绿 / 1-5G绿 / 5-10G黄 / 10-15G紫 / >15G红
      const m = String(size || '').trim().toUpperCase().match(/^([\d.]+)\s*(B|KB|MB|GB|TB)?$/);
      if (!m) return '#67c23a';
      const val = parseFloat(m[1]);
      const unit = m[2] || 'B';
      const gb = unit === 'TB' ? val * 1024
        : unit === 'GB' ? val
        : unit === 'MB' ? val / 1024
        : unit === 'KB' ? val / 1024 / 1024
        : val / 1024 / 1024 / 1024;
      if (gb < 1) return '#2e7d32';
      if (gb < 5) return '#67c23a';
      if (gb < 10) return '#ffb300';
      if (gb < 15) return '#9c27b0';
      return '#e53935';
    },
    formatUptime(sec) {
      if (!sec || sec <= 0) return '-';
      const d = Math.floor(sec / 86400);
      const h = Math.floor((sec % 86400) / 3600);
      const m = Math.floor((sec % 3600) / 60);
      if (d > 0) return d + 'd ' + h + 'h ' + m + 'm';
      if (h > 0) return h + 'h ' + m + 'm';
      return m + 'm';
    },
    toggleDisable(agent) {
      const action = agent.disabled ? '启用' : '禁用';
      ElementPlus.ElMessageBox.confirm('确认' + action + '节点 ' + agent.name + '？', '提示', { type: 'warning' }).then(() => {
        ajax('POST', '/api/cicd/agents/' + agent.id + '/toggle-disable', {}, res => {
          if (res.code === 200) { ElementPlus.ElMessage.success(res.msg); }
          else ElementPlus.ElMessage.error(res.msg || '操作失败');
        });
      }).catch(() => {});
    },
    clearDetailLog() {
      // 仅清空页面日志显示，不删除任何文件
      this.detailLog = '';
      ElementPlus.ElMessage.success('已清空页面日志显示（文件未删除）');
    },
    onAgentCommand(agent, cmd) {
      if (cmd === 'update') this.openUpdateDialog(agent);
      else if (cmd === 'reinstall') this.reinstallAgent(agent);
      else if (cmd === 'reset') this.openCleanupDialog(agent, 'reset');
      else if (cmd === 'uninstall') this.openCleanupDialog(agent, 'uninstall');
    },

    // ─── 详情弹窗 + 折线图 ───────────────────────────────
    openDetail(agent) {
      this.detailAgent = { ...agent, sys_info: agent.sys_info || {} };
      this.detailLog = '';
      this.detailVisible = true;
      // 启动日志 SSE
      this.startDetailLog(agent);
      // 启动指标轮询
      this.startMetricsPolling(agent.id);
      // 初始化图表（DOM 渲染后）
      this.$nextTick(() => { this.initCharts(); });
    },
    closeDetail() {
      this.detailVisible = false;
      this.detailAgent = null;
      if (this.detailLogEs) { this.detailLogEs.close(); this.detailLogEs = null; }
      this.stopMetricsPolling();
      this.destroyCharts();
    },
    startDetailLog(agent) {
      if (this.detailLogEs) { this.detailLogEs.close(); this.detailLogEs = null; }
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/agents/' + agent.id + '/log?follow=true&token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.detailLogEs = es;
      es.onmessage = (evt) => {
        this.detailLog += evt.data.replace(/\\n/g, '\n');
        this.$nextTick(() => {
          const c = this.$refs.detailLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = () => { if (this.detailLogEs === es) { es.close(); this.detailLogEs = null; } };
    },
    startMetricsPolling(agentId) {
      this.stopMetricsPolling();
      var token = localStorage.getItem('auth_token') || '';
      this.metricsEs = new EventSource('/api/cicd/agents/' + agentId + '/metrics?token=' + encodeURIComponent(token));
      this.metricsEs.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (Array.isArray(data)) this.updateCharts(data);
        } catch (err) {}
      };
      this.metricsEs.onerror = () => {};
    },
    stopMetricsPolling() {
      if (this.metricsEs) { this.metricsEs.close(); this.metricsEs = null; }
    },
    initCharts() {
      if (typeof echarts === 'undefined') return;
      const refs = ['chartCpu', 'chartMem', 'chartDisk', 'chartNet', 'chartLoad'];
      const titles = ['CPU 使用率 (%)', '内存使用率 (%)', '磁盘 IO (KB/s)', '网络流量 (KB/s)', '系统负载'];
      refs.forEach((ref, i) => {
        const el = this.$refs[ref];
        if (!el) return;
        const chart = echarts.init(el);
        this.charts[ref] = chart;
        chart.setOption({
          title: { text: titles[i], textStyle: { fontSize: 12, color: '#606266' }, left: 10, top: 5 },
          tooltip: { trigger: 'axis', appendToBody: true, axisPointer: { type: 'line' } },
          grid: { left: 50, right: 40, top: 35, bottom: 25 },
          xAxis: { type: 'category', axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } },
          yAxis: { type: 'value', min: 0, splitLine: { lineStyle: { type: 'dashed' } } },
          series: [],
        });
      });
    },
    destroyCharts() {
      Object.values(this.charts).forEach(c => { try { c.dispose(); } catch(e){} });
      this.charts = {};
    },
    updateCharts(data) {
      if (!data || !data.length) return;
      const labels = data.map((_, i) => i);
      const makeSeries = (name, key, color) => ({
        name, type: 'line', smooth: true, showSymbol: false, lineStyle: { width: 1.5 },
        areaStyle: { opacity: 0.15 }, itemStyle: { color },
        data: data.map(d => d[key] || 0),
      });
      const setOpt = (ref, series) => {
        const chart = this.charts[ref];
        if (!chart) return;
        chart.setOption({ xAxis: { data: labels }, series });
      };
      setOpt('chartCpu', [makeSeries('CPU', 'cpu_load', '#409eff')]);
      setOpt('chartMem', [makeSeries('内存', 'mem_percent', '#67c23a')]);
      setOpt('chartDisk', [makeSeries('读', 'disk_read_kb', '#409eff'), makeSeries('写', 'disk_write_kb', '#e6a23c')]);
      setOpt('chartNet', [makeSeries('收', 'net_rx_kb', '#409eff'), makeSeries('发', 'net_tx_kb', '#e6a23c')]);
      setOpt('chartLoad', [makeSeries('load1', 'load1', '#409eff'), makeSeries('load5', 'load5', '#67c23a'), makeSeries('load15', 'load15', '#e6a23c')]);
      // 更新最新值标签
      const last = data[data.length - 1];
      if (last) this.latestMetrics = { ...last };
    },

    // ─── Docker 缓存管理 ───────────────────────────────

    // ─── Agent 管理（从 CicdConfigPage 迁移） ──────────────
    loadCredentials() {
      ajax('GET', '/api/cicd/credentials', null, res => {
        if (res.code === 200) this.credentials = res.data || [];
      });
    },
    openAgentDialog() {
      this.loadCredentials();
      this.reinstallMode = false;
      this.reinstallAgentId = null;
      this.agentForm = { name: '', host: '', ssh_port: 22, ssh_username: 'root', auth_type: 'credential', ssh_password: '', credential_id: '', master_url: '', work_dir: '/data/cicd', frontend_mount_dir: '', nfs_server: '', nfs_share: '', keep_builds: 5, install_docker: true, harbor_type: 'public', harbor_url: '', harbor_credential_id: '', harbor_ip: '' };
      this.showAgentDialog = true;
    },
    openEditAgent(agent) {
      this.loadCredentials();
      // 全量配置从 detail 接口取（卡片对象仅含列表字段）
      ajax('GET', '/api/cicd/agents/' + agent.id + '/detail', null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '获取配置失败'); return; }
        const d = res.data;
        this.editForm = {
          id: d.id,
          name: d.name || '',
          host: d.host || '',
          ssh_port: d.ssh_port || 22,
          auth_type: d.ssh_auth_type || 'credential',
          credential_id: d.ssh_credential_id || '',
          ssh_username: d.ssh_username || 'root',
          ssh_password: '',
          master_url: d.master_url || '',
          work_dir: d.work_dir || '/data/cicd',
          frontend_mount_dir: d.frontend_mount_dir || '',
          nfs_server: d.nfs_server || '',
          nfs_share: d.nfs_share || '',
          keep_builds: d.keep_builds || 5,
          disabled: !!d.disabled,
          harbor_type: d.harbor_type || 'public',
          harbor_url: d.harbor_url || '',
          harbor_credential_id: d.harbor_credential_id || '',
          harbor_ip: d.harbor_ip || '',
        };
        this.editAgentVisible = true;
      });
    },
    saveEditAgent() {
      if (!this.editForm.name) { ElementPlus.ElMessage.warning('请填写名称'); return; }
      if (!this.editForm.host) { ElementPlus.ElMessage.warning('请填写主机地址'); return; }
      this.savingEdit = true;
      ajax('PUT', '/api/cicd/agents/' + this.editForm.id + '/config', {
        name: this.editForm.name,
        host: this.editForm.host,
        ssh_port: this.editForm.ssh_port,
        ssh_username: this.editForm.ssh_username,
        ssh_auth_type: this.editForm.auth_type,
        ssh_credential_id: this.editForm.credential_id || null,
        master_url: this.editForm.master_url,
        work_dir: this.editForm.work_dir,
        frontend_mount_dir: this.editForm.frontend_mount_dir,
        nfs_server: this.editForm.nfs_server,
        nfs_share: this.editForm.nfs_share,
        keep_builds: this.editForm.keep_builds,
        disabled: this.editForm.disabled,
        harbor_type: this.editForm.harbor_type,
        harbor_url: this.editForm.harbor_url,
        harbor_credential_id: this.editForm.harbor_credential_id || null,
        harbor_ip: this.editForm.harbor_ip,
      }, res => {
        this.savingEdit = false;
        if (res.code === 200) {
          this.editAgentVisible = false;
          ElementPlus.ElMessage.success('Agent 配置已更新');
          this.loadOverview();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      });
    },
    addAgent() {
      if (!this.agentForm.name) { ElementPlus.ElMessage.warning('请填写名称'); return; }
      if (!this.agentForm.host) { ElementPlus.ElMessage.warning('请填写主机地址'); return; }
      if (!this.reinstallMode && this.agentForm.auth_type === 'password' && !this.agentForm.ssh_password) {
        ElementPlus.ElMessage.warning('请填写 SSH 密码'); return;
      }
      if (this.agentForm.auth_type === 'credential' && !this.agentForm.credential_id) {
        ElementPlus.ElMessage.warning('请选择凭据'); return;
      }
      if (!this.agentForm.harbor_url) { ElementPlus.ElMessage.warning('请填写 Harbor 地址'); return; }
      if (!this.agentForm.harbor_credential_id) { ElementPlus.ElMessage.warning('请选择 Harbor 凭据'); return; }
      if (this.agentForm.harbor_type === 'private' && !this.agentForm.harbor_ip) {
        ElementPlus.ElMessage.warning('私有仓库请填写 IP 映射'); return;
      }
      this.saving = true;
      if (this.reinstallMode) {
        ajax('POST', '/api/cicd/agents/' + this.reinstallAgentId + '/install', this.agentForm, res => {
          this.saving = false;
          if (res.code === 200) { this.showAgentDialog = false; this.startInstallStream(res.data.task_id); }
          else ElementPlus.ElMessage.error(res.msg || '启动安装失败');
        });
      } else {
        ajax('POST', '/api/cicd/agents/install-remote', this.agentForm, res => {
          this.saving = false;
          if (res.code === 200) {
            this.showAgentDialog = false;
            this.agentForm = { name: '', host: '', ssh_port: 22, ssh_username: 'root', auth_type: 'credential', ssh_password: '', credential_id: '', master_url: '', work_dir: '/data/cicd', frontend_mount_dir: '', nfs_server: '', nfs_share: '', keep_builds: 5, install_docker: true, harbor_type: 'public', harbor_url: '', harbor_credential_id: '', harbor_ip: '' };
            this.startInstallStream(res.data.task_id);
          } else ElementPlus.ElMessage.error(res.msg || '启动安装失败');
        });
      }
    },
    startInstallStream(taskId, opts) {
      opts = opts || {};
      this.installTitle = opts.title || 'Agent 安装进度';
      this.installStepTitles = opts.steps || ['SSH 连接', '安装 Docker', '上传文件', '启动服务'];
      this.installVisible = true;
      this.installStep = 0;
      this.installLogs = [];
      this.installDone = false;
      clearTimeout(this.installAutoClose);
      if (this.installSource) { this.installSource.close(); }
      const token = localStorage.getItem('auth_token');
      const url = '/api/cicd/agents/install-stream/' + taskId + '?token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.installSource = es;
      es.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        if (data.done) {
          es.close();
          // 操作完成立即刷新概览，让卡片按钮状态（安装/更新/重置）及时变化
          this.loadOverview();
          // 成功：不显示"完成"按钮，停留 1 秒自动关闭；失败/异常保留按钮手动关闭
          clearTimeout(this.installAutoClose);
          this.installAutoClose = setTimeout(() => { this.installVisible = false; }, 1000);
          return;
        }
        if (data.step > 0) {
          this.installStep = data.step - 1;
          if (data.status === 'success' || data.status === 'skipped') this.installStep = data.step;
        }
        const colorMap = { running: '#e6a23c', success: '#67c23a', failed: '#f56c6c', skipped: '#909399', done: '#67c23a' };
        const prefix = data.step_name ? '[' + data.step_name + '] ' : '';
        this.installLogs.push({ text: prefix + (data.message || data.status), color: colorMap[data.status] || '#d4d4d4' });
        if (data.status === 'failed') {
          this.installDone = true;
          es.close();
          this.loadOverview();
        }
      };
      es.onerror = () => { this.installDone = true; es.close(); };
    },
    openUpdateDialog(row) {
      this.updateTarget = row;
      this.updateVisible = true;
    },
    confirmUpdate() {
      const row = this.updateTarget;
      if (!row) return;
      this.saving = true;
      ajax('POST', '/api/cicd/agents/' + row.id + '/update', {}, res => {
        this.saving = false;
        if (res.code === 200) {
          this.updateVisible = false;
          this.startInstallStream(res.data.task_id, { title: 'Agent 更新进度', steps: ['SSH 连接', '上传二进制', '重启服务'] });
        } else ElementPlus.ElMessage.error(res.msg || '启动更新失败');
      });
    },
    reinstallAgent(row) {
      this.loadCredentials();
      ajax('GET', '/api/cicd/agents/' + row.id + '/detail', null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg); return; }
        const d = res.data;
        this.reinstallMode = true;
        this.reinstallAgentId = row.id;
        this.agentForm = {
          name: d.name, host: d.host, ssh_port: d.ssh_port || 22, ssh_username: d.ssh_username || 'root',
          auth_type: d.ssh_auth_type || 'credential', ssh_password: '', credential_id: d.ssh_credential_id || '',
          master_url: d.master_url || '', work_dir: d.work_dir || '/data/cicd', frontend_mount_dir: d.frontend_mount_dir || '',
          nfs_server: d.nfs_server || '', nfs_share: d.nfs_share || '',
          keep_builds: d.keep_builds || 5,
          install_docker: true, harbor_type: d.harbor_type || 'public', harbor_url: d.harbor_url || '',
          harbor_credential_id: d.harbor_credential_id || '', harbor_ip: d.harbor_ip || '',
        };
        this.showAgentDialog = true;
      });
    },
    openCleanupDialog(row, mode) {
      this.cleanupAgent = row;
      this.cleanupMode = mode;
      this.cleanupForm = { remove_docker: false, remove_nfs: (mode === 'uninstall') };
      this.cleanupVisible = true;
    },
    confirmCleanup() {
      const url = '/api/cicd/agents/' + this.cleanupAgent.id + '/' + this.cleanupMode;
      this.saving = true;
      ajax('POST', url, this.cleanupForm, res => {
        this.saving = false;
        if (res.code === 200) {
          this.cleanupVisible = false;
          const isUninstall = this.cleanupMode === 'uninstall';
          this.startInstallStream(res.data.task_id, {
            title: isUninstall ? 'Agent 卸载进度' : 'Agent 重置进度',
            steps: ['SSH 连接', '移除 Agent 服务', '删除工作目录', '卸载 NFS', '卸载 Docker'],
          });
        } else ElementPlus.ElMessage.error(res.msg || '启动失败');
      });
    },
  }
};

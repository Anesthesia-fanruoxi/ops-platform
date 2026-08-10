# 运维平台 - UI 设计文档

> 版本: v1.1
> 更新时间: 2026-07-16
> 维护者: ops-platform 开发团队

---

## 目录

1. [设计概述](#1-设计概述)
2. [页面结构](#2-页面结构)
3. [部署向导页面](#3-部署向导页面)
4. [组件设计](#4-组件设计)
5. [交互流程](#5-交互流程)
6. [API 对接](#6-api-对接)

---

## 1. 设计概述

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| **简洁** | 界面简洁，操作直观 |
| **引导** | 步骤引导，降低学习成本 |
| **反馈** | 实时反馈，状态清晰 |
| **容错** | 错误处理，支持回滚 |

### 1.2 设计风格

- **框架**: Vue 3 + Element Plus
- **配色**: 科技蓝 (#409EFF) + 深色背景
- **字体**: 系统默认字体
- **图标**: Element Plus 内置图标

### 1.3 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  Logo    运维平台                            用户信息    退出  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐  ┌──────────────────────────────────────────┐  │
│  │         │  │                                          │  │
│  │  菜单   │  │                                          │  │
│  │         │  │              内容区域                     │  │
│  │ 部署    │  │                                          │  │
│  │ 管理    │  │                                          │  │
│  │         │  │                                          │  │
│  └─────────┘  └──────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 页面结构

### 2.1 页面列表

| 页面 | 路径 | 说明 |
|------|------|------|
| 部署向导 | /deploy | 一键部署主页面 |
| 项目管理 | /projects | 项目配置管理 |
| 环境管理 | /environments | 环境配置管理 |
| 部署历史 | /deploy-history | 部署记录查看 |
| 系统设置 | /settings | 系统配置 |

### 2.2 菜单结构

```
运维平台
├── 部署管理
│   ├── 一键部署
│   └── 部署历史
├── 项目管理
│   ├── 项目列表
│   └── 环境配置
├── Harbor管理
│   ├── 项目列表
│   └── 镜像仓库
├── Nacos管理
│   ├── 命名空间
│   └── 配置管理
└── 系统设置
    ├── 服务器配置
    └── 通知设置
```

---

## 3. 部署向导页面

### 3.1 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│                      一键部署                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Step 1      Step 2      Step 3      Step 4      Step 5  │   │
│  │    ○───────────○───────────○───────────○───────────○    │   │
│  │  选择项目    选择环境    确认配置    开始部署    完成      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                     │   │
│  │                   当前步骤内容                      │   │
│  │                                                     │   │
│  │                                                     │   │
│  │                                                     │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│                    ┌─────────┐  ┌─────────┐                │
│                    │  上一步  │  │  下一步  │                │
│                    └─────────┘  └─────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Step 1: 选择项目

```
┌─────────────────────────────────────────────────────────────┐
│  选择项目                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  请选择要部署的项目：                                          │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │                 │  │                 │  │                 │  │
│  │      ysh        │  │      jxh        │  │      xafq       │  │
│  │                 │  │                 │  │                 │  │
│  │   15个服务      │  │   14个服务      │  │   14个服务      │  │
│  │                 │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │                 │  │                 │                   │
│  │      ddfq       │  │      ryh        │                   │
│  │                 │  │                 │                   │
│  │   14个服务      │  │   14个服务      │                   │
│  │                 │  │                 │                   │
│  └─────────────────┘  └─────────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Step 2: 选择环境

```
┌─────────────────────────────────────────────────────────────┐
│  选择环境                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  项目: ysh                                                   │
│                                                             │
│  请选择部署模式：                                              │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐  │
│  │  ○ 复制模式                  │  │  ○ 新建模式                  │  │
│  │  从现有环境复制数据            │  │  创建全新环境                │  │
│  └─────────────────────────────┘  └─────────────────────────────┘  │
│                                                             │
│  请选择目标环境：                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │  ○ dev  │  │  ○ test │  │  ○ api  │  │  ○ uat  │       │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘       │
│                                                             │
│  源环境 (仅复制模式)：                                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  请选择源环境...                            ▼        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Step 3: 确认配置

```
┌─────────────────────────────────────────────────────────────┐
│  确认配置                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  基本信息                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  项目名称:  ysh                                      │   │
│  │  目标环境:  api                                      │   │
│  │  部署模式:  复制模式                                  │   │
│  │  源环境:    test                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  端口配置                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  Debug端口:    43300                                 │   │
│  │  服务端口:     43330                                 │   │
│  │  JMX端口:      43360                                 │   │
│  │  中间件端口:   43390                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  服务列表 (15个)                        [展开查看]    │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  app, auth, car, credit, credit-api, es, file,      │   │
│  │  gateway, job, judgment, market, request,           │   │
│  │  signature, sms, system                             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  中间件列表 (5个)                      [展开查看]    │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  nacos, mysql-nfs, redis, mysql, rabbitmq           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 Step 4: 开始部署

```
┌─────────────────────────────────────────────────────────────┐
│  开始部署                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  部署进度: 40%                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  部署步骤                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  ✅ 1. 生成YAML配置文件              完成            │   │
│  │  ✅ 2. 创建NFS目录结构               完成            │   │
│  │  ⏳ 3. 复制环境数据                  进行中...       │   │
│  │  ⬜ 4. 创建Harbor项目                等待中          │   │
│  │  ⬜ 5. 启动中间件                    等待中          │   │
│  │  ⬜ 6. 创建PersistentVolume          等待中          │   │
│  │  ⬜ 7. 启动微服务                    等待中          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  实时日志                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  [2026-07-07 16:30:01] 开始复制目录...                │   │
│  │  [2026-07-07 16:30:02] 复制 /data/logs/ysh-test...   │   │
│  │  [2026-07-07 16:30:05] 目录复制完成                  │   │
│  │  [2026-07-07 16:30:06] 复制Nacos配置...              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│                    ┌─────────┐                              │
│                    │  取消部署 │                              │
│                    └─────────┘                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.6 Step 5: 完成

```
┌─────────────────────────────────────────────────────────────┐
│  部署完成                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                    ┌─────────────────┐                      │
│                    │                 │                      │
│                    │      ✅        │                      │
│                    │                 │                      │
│                    └─────────────────┘                      │
│                                                             │
│                    部署成功！                                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  部署信息                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  项目名称:  ysh-api                                  │   │
│  │  部署时间:  2026-07-07 16:35:00                      │   │
│  │  耗时:      5分钟                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  服务状态                                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  ✅ ysh-app        运行中                            │   │
│  │  ✅ ysh-auth       运行中                            │   │
│  │  ✅ ysh-gateway    运行中                            │   │
│  │  ... (共15个服务)                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                    │
│  │ 查看详情 │  │ 访问应用 │  │ 返回首页 │                    │
│  └─────────┘  └─────────┘  └─────────┘                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 组件设计

### 4.1 步骤条组件

```vue
<template>
  <div class="deploy-steps">
    <el-steps :active="currentStep" finish-status="success">
      <el-step title="选择项目" icon="el-icon-folder" />
      <el-step title="选择环境" icon="el-icon-map-location" />
      <el-step title="确认配置" icon="el-icon-document-checked" />
      <el-step title="开始部署" icon="el-icon-upload" />
      <el-step title="完成" icon="el-icon-check" />
    </el-steps>
  </div>
</template>
```

### 4.2 项目选择组件

```vue
<template>
  <div class="project-selector">
    <div class="project-grid">
      <div 
        v-for="project in projects" 
        :key="project.name"
        :class="['project-card', { selected: selectedProject === project.name }]"
        @click="selectProject(project)"
      >
        <div class="project-icon">📦</div>
        <div class="project-name">{{ project.name }}</div>
        <div class="project-info">{{ project.services.length }}个服务</div>
      </div>
    </div>
  </div>
</template>
```

### 4.3 环境选择组件

```vue
<template>
  <div class="env-selector">
    <div class="mode-selector">
      <el-radio-group v-model="deployMode">
        <el-radio-button label="copy">
          <el-icon><el-icon-copy /></el-icon>
          复制模式
        </el-radio-button>
        <el-radio-button label="create">
          <el-icon><el-icon-plus /></el-icon>
          新建模式
        </el-radio-button>
      </el-radio-group>
    </div>
    
    <div class="env-grid">
      <div 
        v-for="env in environments" 
        :key="env.name"
        :class="['env-card', { selected: selectedEnv === env.name }]"
        @click="selectEnv(env)"
      >
        <div class="env-name">{{ env.name }}</div>
        <div class="env-domain">{{ env.domain }}</div>
      </div>
    </div>
    
    <div v-if="deployMode === 'copy'" class="source-env">
      <el-select v-model="sourceEnv" placeholder="选择源环境">
        <el-option 
          v-for="env in availableSourceEnvs" 
          :key="env" 
          :label="env" 
          :value="env" 
        />
      </el-select>
    </div>
  </div>
</template>
```

### 4.4 确认配置组件

```vue
<template>
  <div class="config-confirm">
    <el-collapse>
      <el-collapse-item title="基本信息">
        <div class="config-item">
          <span class="label">项目名称:</span>
          <span class="value">{{ project.name }}</span>
        </div>
        <div class="config-item">
          <span class="label">目标环境:</span>
          <span class="value">{{ env.name }}</span>
        </div>
        <div class="config-item">
          <span class="label">部署模式:</span>
          <span class="value">{{ deployMode === 'copy' ? '复制模式' : '新建模式' }}</span>
        </div>
      </el-collapse-item>
      
      <el-collapse-item title="端口配置">
        <div class="config-item">
          <span class="label">Debug端口:</span>
          <span class="value">{{ env.debug_port }}</span>
        </div>
        <div class="config-item">
          <span class="label">服务端口:</span>
          <span class="value">{{ env.node_port }}</span>
        </div>
        <div class="config-item">
          <span class="label">JMX端口:</span>
          <span class="value">{{ env.jmx_port }}</span>
        </div>
        <div class="config-item">
          <span class="label">中间件端口:</span>
          <span class="value">{{ env.middleware_port }}</span>
        </div>
      </el-collapse-item>
      
      <el-collapse-item title="服务列表">
        <el-tag 
          v-for="service in project.services" 
          :key="service.name"
          type="info"
        >
          {{ service.name }} ({{ service.xms }}g/{{ service.xmx }}g)
        </el-tag>
      </el-collapse-item>
      
      <el-collapse-item title="中间件列表">
        <el-tag 
          v-for="middleware in project.middleware" 
          :key="middleware"
          type="warning"
        >
          {{ middleware }}
        </el-tag>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
```

### 4.5 部署进度组件

```vue
<template>
  <div class="deploy-progress">
    <el-progress 
      :percentage="progress" 
      :status="progressStatus"
      :stroke-width="20"
    />
    
    <div class="deploy-steps">
      <div 
        v-for="step in steps" 
        :key="step.name"
        :class="['step-item', step.status]"
      >
        <el-icon v-if="step.status === 'success'"><el-icon-check /></el-icon>
        <el-icon v-else-if="step.status === 'running'"><el-icon-loading /></el-icon>
        <el-icon v-else-if="step.status === 'failed'"><el-icon-close /></el-icon>
        <el-icon v-else><el-icon-time /></el-icon>
        <span class="step-name">{{ step.name }}</span>
        <span class="step-status">{{ step.statusText }}</span>
      </div>
    </div>
    
    <div class="deploy-logs">
      <div class="log-header">实时日志</div>
      <div class="log-content" ref="logContainer">
        <div v-for="(log, index) in logs" :key="index" class="log-line">
          [{{ log.time }}] {{ log.message }}
        </div>
      </div>
    </div>
  </div>
</template>
```

---

## 5. 交互流程

### 5.1 页面加载

```
1. 页面初始化
   ↓
2. 调用 GET /api/deploy/list-projects
   ↓
3. 获取项目列表
   ↓
4. 渲染项目选择卡片
```

### 5.2 选择项目

```
1. 用户点击项目卡片
   ↓
2. 调用 GET /api/deploy/list-envs/{project}
   ↓
3. 获取环境列表
   ↓
4. 切换到环境选择步骤
```

### 5.3 选择环境

```
1. 用户选择部署模式
   ↓
2. 用户选择目标环境
   ↓
3. 如果是复制模式，选择源环境
   ↓
4. 切换到确认配置步骤
```

### 5.4 确认配置

```
1. 显示配置摘要
   ↓
2. 用户确认配置
   ↓
3. 切换到部署步骤
   ↓
4. 调用 POST /api/deploy/deploy
```

### 5.5 部署过程

```
1. 建立WebSocket连接
   ↓
2. 接收实时进度
   ↓
3. 更新进度条
   ↓
4. 更新日志
   ↓
5. 部署完成
   ↓
6. 切换到完成步骤
```

### 5.6 错误处理

```
1. 部署失败
   ↓
2. 显示错误信息
   ↓
3. 提供重试按钮
   ↓
4. 提供回滚按钮
```

---

## 6. API 对接

### 6.1 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/deploy/list-projects` | GET | 获取项目列表 |
| `/api/deploy/list-envs/{project}` | GET | 获取环境列表 |
| `/api/deploy/get-project-config/{project}` | GET | 获取项目配置 |
| `/api/deploy/deploy` | POST | 一键部署 |
| `/api/deploy/deploy-status/{task_id}` | GET | 查询部署状态 |
| `/api/deploy/deploy-log/{task_id}` | GET | 获取部署日志 |

### 6.2 数据结构

**项目列表**

```json
{
  "code": 200,
  "data": ["ysh", "jxh", "xafq", "ddfq", "ryh"]
}
```

**环境列表**

```json
{
  "code": 200,
  "data": ["dev", "test", "api", "uat"]
}
```

**项目配置**

```json
{
  "code": 200,
  "data": {
    "name": "ysh",
    "services": [
      {"name": "app", "xms": 2, "xmx": 8, "replicas": 1}
    ],
    "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
    "envs": {
      "api": {
        "tag": "202607070901",
        "nacos_namespace": "9bd04ce8-9565-419c-bebe-93bd81411fbf",
        "domain": "yshapi.hzbxhd.com",
        "debug_port": 43300,
        "node_port": 43330,
        "jmx_port": 43360,
        "middleware_port": 43390
      }
    }
  }
}
```

**部署请求**

```json
{
  "project_name": "ysh",
  "env_name": "api",
  "mode": "copy",
  "source_env": "test"
}
```

**部署响应**

```json
{
  "code": 200,
  "data": {
    "task_id": "deploy_20260707_163500",
    "status": "running",
    "progress": 40,
    "steps": [
      {
        "name": "generate_yaml",
        "status": "success",
        "data": {...}
      }
    ]
  }
}
```

---

## 附录

### A. 颜色规范

| 颜色 | 用途 | 色值 |
|------|------|------|
| 主色 | 按钮、链接 | #409EFF |
| 成功色 | 成功状态 | #67C23A |
| 警告色 | 警告状态 | #E6A23C |
| 危险色 | 错误状态 | #F56C6C |
| 信息色 | 信息提示 | #909399 |

### B. 图标规范

| 图标 | 用途 |
|------|------|
| el-icon-folder | 项目 |
| el-icon-map-location | 环境 |
| el-icon-document-checked | 确认 |
| el-icon-upload | 部署 |
| el-icon-check | 完成 |
| el-icon-loading | 进行中 |
| el-icon-close | 失败 |
| el-icon-time | 等待 |

### C. 响应式断点

| 断点 | 宽度 | 说明 |
|------|------|------|
| xs | <576px | 手机 |
| sm | ≥576px | 平板 |
| md | ≥768px | 小桌面 |
| lg | ≥992px | 桌面 |
| xl | ≥1200px | 大桌面 |

---

**文档版本**: v1.0  
**更新时间**: 2026-07-07  
**维护者**: ops-platform 开发团队

# -*- coding: utf-8 -*-
"""
CI/CD 构建域模型：GitCredential / DockerfileTemplate / CicdFlowTemplate / BuildAgent / Build / ScheduleLog
"""
from datetime import datetime

from core.db import db


class GitCredential(db.Model):
    """凭据（secret 落库 AES 加密）"""
    __tablename__ = 'cicd_credentials'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(20), nullable=False, default='password')  # password | token | ssh_key | harbor
    username = db.Column(db.String(100), default='')
    secret = db.Column(db.Text, default='')  # AES 加密后的密文
    url = db.Column(db.String(200), default='')  # harbor 类型: 仓库地址
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self, include_secret=False):
        data = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'username': self.username,
            'url': self.url or '',
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
        if include_secret:
            data['secret'] = self.secret
        return data


class DockerfileTemplate(db.Model):
    """Dockerfile 可复用模板（带占位符）"""
    __tablename__ = 'cicd_dockerfile_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    project_type = db.Column(db.String(20), default='java')  # java | node | go
    base_image = db.Column(db.String(200), default='')
    content = db.Column(db.Text, default='')  # 带占位符的 Dockerfile 模板
    is_builtin = db.Column(db.Boolean, default=False)
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'project_type': self.project_type,
            'base_image': self.base_image,
            'content': self.content,
            'is_builtin': self.is_builtin,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class ScheduleLog(db.Model):
    """调度日志：记录每次构建触发的调度决策过程"""
    __tablename__ = 'cicd_schedule_logs'

    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.Integer, db.ForeignKey('cicd_builds.id'), nullable=True)
    build_no = db.Column(db.String(50), default='')
    project_name = db.Column(db.String(100), default='')
    environment_name = db.Column(db.String(100), default='')
    branch = db.Column(db.String(200), default='')
    triggered_by = db.Column(db.String(80), default='')
    # 调度结果：dispatching | dispatched | no_agent | failed
    status = db.Column(db.String(20), default='dispatching')
    selected_agent = db.Column(db.String(100), default='')  # 最终选中的节点名
    detail_logs = db.Column(db.Text, default='')  # 详细调度日志（按行存储）
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        """列表用：基本信息"""
        return {
            'id': self.id,
            'build_id': self.build_id,
            'build_no': self.build_no,
            'project_name': self.project_name,
            'environment_name': self.environment_name,
            'branch': self.branch,
            'triggered_by': self.triggered_by,
            'status': self.status,
            'selected_agent': self.selected_agent,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def to_detail_dict(self):
        """详情用：含完整日志"""
        d = self.to_dict()
        d['detail_logs'] = self.detail_logs or ''
        return d


class CicdFlowTemplate(db.Model):
    """CI/CD 流程大模板（项目级，1:1 关联 project，分步配置）"""
    __tablename__ = 'cicd_flow_templates'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), unique=True, nullable=False)

    # Step1: 基本信息
    project_type = db.Column(db.String(20), default='backend')  # frontend | backend
    language = db.Column(db.String(30), default='java')  # 前端: vue/react  后端: java/go/python

    # Step2: Git 拉取
    git_docker_image = db.Column(db.String(200), default='')  # 如 alpine/git:latest
    git_url = db.Column(db.String(300), default='')
    git_credential_id = db.Column(db.Integer, db.ForeignKey('cicd_credentials.id'), nullable=True)

    # Step3: 编译
    build_docker_image = db.Column(db.String(200), default='')  # 如 maven:3.9-eclipse-temurin-17
    build_command = db.Column(db.Text, default='')  # 如 mvn clean package -DskipTests

    # Step4: 产物收集（后端多行目录，前端默认 dist）
    artifact_dirs = db.Column(db.Text, default='')  # 按行分割，服务目录列表
    artifact_dir = db.Column(db.String(200), default='')  # 产物目录：各服务内统一的产物相对路径，如 target/pkg

    # Step5: Docker Build（后端）
    dockerfile_template_id = db.Column(db.Integer, db.ForeignKey('cicd_dockerfile_templates.id'), nullable=True)
    image_name = db.Column(db.String(200), default='')

    # 通用
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    project = db.relationship('Project', backref=db.backref('cicd_template', uselist=False, lazy=True))
    credential = db.relationship('GitCredential', lazy=True)
    dockerfile_template = db.relationship('DockerfileTemplate', lazy=True)

    def get_artifact_dir_list(self):
        """解析产物目录列表"""
        if self.project_type == 'frontend':
            return ['dist']
        dirs = [line.strip() for line in (self.artifact_dirs or '').splitlines() if line.strip()]
        return dirs

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else '',
            'project_type': self.project_type,
            'language': self.language,
            'git_docker_image': self.git_docker_image,
            'git_url': self.git_url,
            'git_credential_id': self.git_credential_id,
            'git_credential_name': self.credential.name if self.credential else '',
            'build_docker_image': self.build_docker_image,
            'build_command': self.build_command,
            'artifact_dirs': self.artifact_dirs,
            'artifact_dir_list': self.get_artifact_dir_list(),
            'artifact_dir': self.artifact_dir,
            'dockerfile_template_id': self.dockerfile_template_id,
            'dockerfile_template_name': self.dockerfile_template.name if self.dockerfile_template else '',
            'image_name': self.image_name,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class BuildAgent(db.Model):
    """构建节点（仅存安装配置；在线/指标/负载全部在 Redis 心跳中）"""
    __tablename__ = 'cicd_agents'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    host = db.Column(db.String(100), default='')
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    install_status = db.Column(db.Boolean, default=False)  # True=已安装 False=未安装/已重置
    disabled = db.Column(db.Boolean, default=False)  # 手动禁用，禁止调度
    max_concurrent = db.Column(db.Integer, default=2)
    port = db.Column(db.Integer, default=9090)  # Agent 任务/日志监听端口
    # SSH 连接信息（安装时保存，重置/卸载复用）
    ssh_port = db.Column(db.Integer, default=22)
    ssh_username = db.Column(db.String(50), default='root')
    ssh_auth_type = db.Column(db.String(20), default='credential')  # credential | password
    ssh_credential_id = db.Column(db.Integer, nullable=True)
    work_dir = db.Column(db.String(200), default='/data/cicd')
    master_url = db.Column(db.String(200), default='')  # Master 回推地址
    keep_builds = db.Column(db.Integer, default=5)  # 构建记录/目录保留数（每节点独立，超出同步清理 Master 与节点目录）
    # Harbor 凭据（安装时配置，关联凭据表）
    harbor_credential_id = db.Column(db.Integer, nullable=True)
    harbor_type = db.Column(db.String(20), default='public')  # public | private
    harbor_url = db.Column(db.String(200), default='')
    harbor_user = db.Column(db.String(100), default='')
    harbor_pass = db.Column(db.Text, default='')  # AES 加密后的密文
    harbor_ip = db.Column(db.String(50), default='')  # 私有仓库 IP 映射
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        """列表用：只返回安装配置字段（在线/指标由 Redis 心跳组装）"""
        return {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'install_status': bool(self.install_status),
            'disabled': self.disabled or False,
            'max_concurrent': self.max_concurrent,
            'port': self.port or 9090,
            'harbor_url': self.harbor_url or '',
            'work_dir': self.work_dir or '/data/cicd',
        }

    def to_detail_dict(self):
        """详情用：安装/重装回填所需全部字段"""
        d = self.to_dict()
        d.update({
            'ssh_port': self.ssh_port or 22,
            'ssh_username': self.ssh_username or 'root',
            'ssh_auth_type': self.ssh_auth_type or 'credential',
            'ssh_credential_id': self.ssh_credential_id,
            'master_url': self.master_url or '',
            'harbor_type': self.harbor_type or 'public',
            'harbor_credential_id': self.harbor_credential_id,
            'harbor_ip': self.harbor_ip or '',
            'keep_builds': self.keep_builds or 5,
        })
        return d

class Build(db.Model):
    """构建记录（执行记录：执行人/结果/日志）"""
    __tablename__ = 'cicd_builds'

    id = db.Column(db.Integer, primary_key=True)
    build_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    environment_id = db.Column(db.Integer, db.ForeignKey('environments.id'), nullable=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('cicd_agents.id'), nullable=True)
    branch = db.Column(db.String(200), default='master')
    project_type = db.Column(db.String(20), default='backend')  # frontend | backend
    language = db.Column(db.String(30), default='')  # 快照
    steps_snapshot = db.Column(db.Text, default='')  # 完整步骤配置 JSON 快照
    image_name = db.Column(db.String(200), default='')
    image_tag = db.Column(db.String(100), default='')
    image_digest = db.Column(db.String(200), default='')
    status = db.Column(db.String(20), default='pending')  # pending|running|success|failed|cancelled
    cancel_requested = db.Column(db.Boolean, default=False)  # 取消意图标记
    log_file = db.Column(db.String(300), default='')
    triggered_by = db.Column(db.String(80), default='')  # 执行人
    error_msg = db.Column(db.Text, default='')
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration = db.Column(db.Float, nullable=True)  # 秒
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联（仅用于联表展示）
    project = db.relationship('Project', lazy=True)
    environment = db.relationship('Environment', lazy=True)
    agent = db.relationship('BuildAgent', lazy=True)

    def get_steps_snapshot(self):
        """解析步骤快照 JSON"""
        import json
        if self.steps_snapshot:
            try:
                return json.loads(self.steps_snapshot)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def to_dict(self):
        return {
            'id': self.id,
            'build_no': self.build_no,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else '',
            'environment_id': self.environment_id,
            'environment_name': self.environment.name if self.environment else '',
            'agent_id': self.agent_id,
            'agent_name': self.agent.name if self.agent else '',
            'branch': self.branch,
            'project_type': self.project_type,
            'language': self.language,
            'image_name': self.image_name,
            'image_tag': self.image_tag,
            'image_digest': self.image_digest,
            'status': self.status,
            'triggered_by': self.triggered_by,
            'error_msg': self.error_msg,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            'finished_at': self.finished_at.strftime('%Y-%m-%d %H:%M:%S') if self.finished_at else None,
            'duration': round(self.duration, 1) if self.duration else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

# -*- coding: utf-8 -*-
"""
Dockerfile 模板服务：CRUD + 占位符渲染
"""
from modules.cicd.models import DockerfileTemplate


def render_dockerfile(template_content, variables):
    """
    渲染 Dockerfile 模板占位符 {{key}}
    variables: dict，如 {'base_image': '...', 'artifact_name': '...', 'port': '8080'}
    """
    result = template_content
    for key, value in variables.items():
        result = result.replace('{{' + key + '}}', str(value))
    return result


def render_for_build(dockerfile_template_id, build_context):
    """
    为构建渲染 Dockerfile 内容
    build_context: dict 含 image_name, project_type, build_command, workdir, jar_name, java_opts 等
    """
    tpl = DockerfileTemplate.query.get(dockerfile_template_id) if dockerfile_template_id else None
    if not tpl:
        return ''
    project_name = build_context.get('project_name', '')
    # 镜像名规范改为由 Agent 按 {project}-{env}/{svcName} 自动生成，image_name 不再手填；
    # 为空时回退 project_name，保证 Dockerfile 的 artifact_name/jar_name/workdir 变量不为空
    image_name = build_context.get('image_name') or project_name or 'app'
    # 注意：jar 相关占位符不在 Master 侧渲染，保留 {{jar_name}}（含扩展名的真实文件名，如 ysh-gateway.jar，模板直接引用不追加 .jar）
    # 与 {{jar_path}}（相对构建上下文的路径，如 pkg/ysh-gateway.jar）下发 Agent，由 Agent 逐服务识别实际 jar 后替换。
    variables = {
        'base_image': tpl.base_image or '',
        'artifact_name': image_name,
        'workdir': '{{workdir}}',  # 保留原文，由 Agent 端替换为实际服务名
        'java_opts': build_context.get('java_opts', '-server -Xms2g -Xmx8g -XX:CompressedClassSpaceSize=2g -XX:MaxMetaspaceSize=2g -XX:+UseG1GC'),
        'port': build_context.get('port', '8080'),
        'project_name': project_name,
    }
    return render_dockerfile(tpl.content, variables)

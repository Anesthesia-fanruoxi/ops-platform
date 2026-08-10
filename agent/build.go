package main

// ─── 构建执行管线（动态步骤：clone → build → collect → docker_build → docker_push）───

import (
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// keepBuilds 工作目录中保留的最近构建目录数量（含当前构建），超出的旧目录自动清理
const keepBuilds = 5

// ─── 构建任务结构 ────────────────────────────────────────────────

type BuildTask struct {
	BuildID         int            `json:"build_id"`
	BuildNo         string         `json:"build_no"`
	ProjectEnv      string         `json:"project_env"` // "{project}-{env}" 工作子目录名
	ProjectType     string         `json:"project_type"` // "frontend" | "backend"
	Language        string         `json:"language"`
	Branch          string         `json:"branch"`
	Steps           StepConfig     `json:"steps"`
	Harbor          HarborCfg      `json:"harbor"`
	CancelRequested bool           `json:"cancel_requested"`
	StartStep       int            `json:"start_step"` // 重跑起点：默认 1 从头执行；>1 复用已有目录从该步骤续跑
	KeepBuilds      int            `json:"keep_builds"` // 构建保留数：Master 下发，用于清理旧构建目录；未设置(<1)回退默认值
}

type StepConfig struct {
	GitDockerImage    string         `json:"git_docker_image"`
	GitURL            string         `json:"git_url"`
	GitCredential     *GitCredential `json:"git_credential"`
	BuildDockerImage  string         `json:"build_docker_image"`
	BuildCommand      string         `json:"build_command"`
	ArtifactDirs      []string       `json:"artifact_dirs"`
	ArtifactDir       string         `json:"artifact_dir"` // 产物目录：各服务内统一的产物相对路径，如 target/pkg
	DockerfileContent string         `json:"dockerfile_content"`
	ImageName         string         `json:"image_name"`
	ImageTag          string         `json:"image_tag"`
}

type GitCredential struct {
	Type     string `json:"type"`
	Username string `json:"username"`
	Secret   string `json:"secret"`
}

type HarborCfg struct {
	URL  string `json:"url"`
	User string `json:"user"`
	Pass string `json:"pass"`
}

// ─── 步骤定义 ────────────────────────────────────────────────────

type StepDef struct {
	No   int
	Key  string
	Name string
}

func getStepsDef(projectType string) []StepDef {
	if projectType == "frontend" {
		return []StepDef{
			{1, "clone", "Git Clone"},
			{2, "build", "编译构建"},
			{3, "collect", "产物收集"},
		}
	}
	return []StepDef{
		{1, "clone", "Git Clone"},
		{2, "build", "编译构建"},
		{3, "collect", "产物收集"},
		{4, "docker_build", "Docker Build"},
		{5, "docker_push", "Docker Push"},
	}
}

// ─── 构建主流程 ──────────────────────────────────────────────────

func executeBuild(task *BuildTask) {
	log.Printf("[Build#%d] 开始执行 type=%s branch=%s start_step=%d", task.BuildID, task.ProjectType, task.Branch, task.StartStep)
	logTaskSummary(task)

	// 取消控制器：登记本次构建的 runner，收到 Master 取消推送时即时终止运行中的命令
	runner := newBuildRunner(task.BuildID)
	registerRunner(runner)
	defer unregisterRunner(runner)

	// 目录结构：{WorkDir}/{project}-{env}/{buildNo}/{code,product,logs}
	projEnvDir := filepath.Join(cfg.WorkDir, task.ProjectEnv)
	buildDir := filepath.Join(projEnvDir, task.BuildNo)
	codeDir := filepath.Join(buildDir, "code")
	productDir := filepath.Join(buildDir, "product")
	logDir := filepath.Join(buildDir, "logs")

	// 重跑起点：<1 视为从头执行
	startStep := task.StartStep
	if startStep < 1 {
		startStep = 1
	}

	if startStep > 1 {
		// 重跑：保留已有构建目录（复用代码/产物），仅校验与补齐；目录被清理则无法续跑
		if _, err := os.Stat(codeDir); err != nil {
			sendResult(task.BuildID, "failed", "", "构建目录已被清理，无法重跑，请重新触发完整构建")
			return
		}
		os.MkdirAll(productDir, 0755)
		os.MkdirAll(logDir, 0755)
	} else {
		os.RemoveAll(buildDir)
		os.MkdirAll(codeDir, 0755)
		os.MkdirAll(productDir, 0755)
		os.MkdirAll(logDir, 0755)
	}

	steps := getStepsDef(task.ProjectType)
	success := true
	errMsg := ""
	digest := ""
	var cancelled bool
	var images []string

	// 单文件日志：所有步骤写入 logs/build.log，以 === 标签分隔（重跑时追加于历史之后）
	stepLog := newStepLogger(logDir)
	defer stepLog.close()

	// 若因取消被终止，上报并结束构建（各步骤错误分支优先检查）
	abortIfCancelled := func(stepNo int, stepKey string) bool {
		if !runner.isKilled() {
			return false
		}
		stepLog.log("[CANCELLED] 构建已取消")
		sendStep(task.BuildID, stepNo, stepKey, "failed", "构建已取消")
		sendResult(task.BuildID, "failed", "", "构建已取消")
		return true
	}

	// Step 1: Git Clone（Docker 容器化）
	if startStep <= 1 {
		cancelled = sendStep(task.BuildID, 1, "clone", "running", "")
		if cancelled {
			sendResult(task.BuildID, "failed", "", "构建已取消")
			return
		}
		stepLog.log(fmt.Sprintf("=== Git Clone ===\n分支: %s\nURL: %s\nDocker镜像: %s\n", task.Branch, task.Steps.GitURL, task.Steps.GitDockerImage))
		if err := execGitClone(runner, stepLog, task, codeDir); err != nil {
			if abortIfCancelled(1, "clone") {
				return
			}
			success = false
			errMsg = "git clone 失败: " + err.Error()
			stepLog.log("[ERROR] " + errMsg)
			sendStep(task.BuildID, 1, "clone", "failed", errMsg)
		} else {
			sendStep(task.BuildID, 1, "clone", "success", "")
		}
	}

	// Step 2: 编译构建（Docker 容器化）
	if startStep <= 2 {
		if success && task.Steps.BuildCommand != "" {
			cancelled = sendStep(task.BuildID, 2, "build", "running", "")
			if cancelled {
				sendResult(task.BuildID, "failed", "", "构建已取消")
				return
			}
			stepLog.log(fmt.Sprintf("\n=== 编译构建 ===\nDocker镜像: %s\n命令: %s\n", task.Steps.BuildDockerImage, task.Steps.BuildCommand))
			if err := execBuild(runner, stepLog, task, codeDir); err != nil {
				if abortIfCancelled(2, "build") {
					return
				}
				success = false
				errMsg = "编译构建失败: " + err.Error()
				stepLog.log("[ERROR] " + errMsg)
				sendStep(task.BuildID, 2, "build", "failed", errMsg)
			} else {
				sendStep(task.BuildID, 2, "build", "success", "")
			}
		} else if success {
			sendStep(task.BuildID, 2, "build", "success", "")
		}
	}

	// Step 3: 产物收集
	if startStep <= 3 && success {
		cancelled = sendStep(task.BuildID, 3, "collect", "running", "")
		if cancelled {
			sendResult(task.BuildID, "failed", "", "构建已取消")
			return
		}
		stepLog.log(fmt.Sprintf("\n=== 产物收集 ===\n服务目录: %s\n产物目录: %s\n", strings.Join(task.Steps.ArtifactDirs, ", "), task.Steps.ArtifactDir))
		if err := execCollectArtifacts(stepLog, task, codeDir, productDir); err != nil {
			if abortIfCancelled(3, "collect") {
				return
			}
			success = false
			errMsg = "产物收集失败: " + err.Error()
			stepLog.log("[ERROR] " + errMsg)
			sendStep(task.BuildID, 3, "collect", "failed", errMsg)
		} else {
			sendStep(task.BuildID, 3, "collect", "success", "")
		}
	}

	// Step 4 & 5: Docker Build + Push（仅后端）
	if success && task.ProjectType == "backend" {
		// 构建前清理当前项目环境的旧镜像（非致命，保留最新一个）
		if startStep <= 4 {
			execCleanupImages(runner, stepLog, task)
		}
		// Step 4: Docker Build（多线程）
		if startStep <= 4 {
			cancelled = sendStep(task.BuildID, 4, "docker_build", "running", "")
			if cancelled {
				sendResult(task.BuildID, "failed", "", "构建已取消")
				return
			}
			stepLog.log(fmt.Sprintf("\n=== Docker Build ===\n命名空间: %s/%s\nTag: %s\n", task.Harbor.URL, strings.ToLower(task.ProjectEnv), task.Steps.ImageTag))
			var err error
			images, err = execDockerBuild(runner, stepLog, task, productDir)
			if err != nil {
				if abortIfCancelled(4, "docker_build") {
					return
				}
				success = false
				errMsg = "docker build 失败: " + err.Error()
				stepLog.log("[ERROR] " + errMsg)
				sendStep(task.BuildID, 4, "docker_build", "failed", errMsg)
			} else {
				sendStep(task.BuildID, 4, "docker_build", "success", "")
			}
		} else {
			// 从 Step5 重跑：跳过构建，从产物目录重建镜像列表（上次构建的镜像仍在本地 docker）
			images = listBuiltImages(task, productDir)
			log.Printf("[Build#%d] 重跑跳过 Docker Build，复用已有镜像 %d 个", task.BuildID, len(images))
			if len(images) == 0 {
				success = false
				errMsg = "未找到可推送的镜像（产物目录可能已被清理），请从 Docker Build 重跑"
				sendStep(task.BuildID, 5, "docker_push", "failed", errMsg)
			}
		}

		// Step 5: Docker Push
		if success && startStep <= 5 {
			if task.Harbor.URL != "" {
				cancelled = sendStep(task.BuildID, 5, "docker_push", "running", "")
				if cancelled {
					sendResult(task.BuildID, "failed", "", "构建已取消")
					return
				}
				stepLog.log(fmt.Sprintf("\n=== Docker Push ===\nRegistry: %s\n镜像数: %d\n", task.Harbor.URL, len(images)))
				if err := execDockerPush(runner, stepLog, task, images); err != nil {
					if abortIfCancelled(5, "docker_push") {
						return
					}
					success = false
					errMsg = "docker push 失败: " + err.Error()
					stepLog.log("[ERROR] " + errMsg)
					sendStep(task.BuildID, 5, "docker_push", "failed", errMsg)
				} else {
					if len(images) > 0 {
						digest = getImageDigest(images[0])
					}
					sendStep(task.BuildID, 5, "docker_push", "success", "")
				}
			} else {
				sendStep(task.BuildID, 5, "docker_push", "success", "")
			}
		}
	}

	// 回调最终结果
	status := "success"
	if !success {
		status = "failed"
	}
	sendResult(task.BuildID, status, digest, errMsg)
	log.Printf("[Build#%d] 完成 status=%s", task.BuildID, status)

	// 保留最近构建目录（含本次），便于在工作目录查阅代码与产物；保留数跟随 Master 下发，未设置回退默认值
	keep := task.KeepBuilds
	if keep < 1 {
		keep = keepBuilds
	}
	cleanupOldBuilds(projEnvDir, keep)
	_ = steps
}

// listBuiltImages 按镜像命名规范从产物目录重建镜像列表（用于从 Docker Push 重跑时复用已构建镜像）
func listBuiltImages(task *BuildTask, productDir string) []string {
	entries, err := os.ReadDir(productDir)
	if err != nil {
		return nil
	}
	var images []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		images = append(images, fmt.Sprintf("%s/%s:%s", task.Harbor.URL, strings.ToLower(task.ProjectEnv+"/"+e.Name()), task.Steps.ImageTag))
	}
	return images
}

// cleanupOldBuilds 按修改时间降序保留 projEnvDir 下最近 keep 个构建目录，删除更旧的
func cleanupOldBuilds(projEnvDir string, keep int) {
	entries, err := os.ReadDir(projEnvDir)
	if err != nil {
		return
	}
	type buildEntry struct {
		name    string
		modTime time.Time
	}
	var builds []buildEntry
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		info, infoErr := e.Info()
		if infoErr != nil {
			continue
		}
		builds = append(builds, buildEntry{name: e.Name(), modTime: info.ModTime()})
	}
	log.Printf("[Cleanup] 目录=%s 当前构建数=%d 保留数=%d", projEnvDir, len(builds), keep)
	sort.Slice(builds, func(i, j int) bool { return builds[i].modTime.After(builds[j].modTime) })
	for i := keep; i < len(builds); i++ {
		os.RemoveAll(filepath.Join(projEnvDir, builds[i].name))
		log.Printf("[Cleanup] 已清理旧构建目录: %s (mtime=%s)", builds[i].name, builds[i].modTime.Format("2006-01-02 15:04:05"))
	}
}

// ─── 任务内容摘要（脱敏）─────────────────────────────────────────

// logTaskSummary 输出接收到的完整任务配置（凭据脱敏），便于核对 Master 下发的任务体
func logTaskSummary(task *BuildTask) {
	credType := "none"
	if task.Steps.GitCredential != nil {
		credType = task.Steps.GitCredential.Type
	}
	log.Printf("[Build#%d] ── 接收任务配置 ──", task.BuildID)
	log.Printf("[Build#%d]   项目类型=%s 语言=%s 分支=%s", task.BuildID, task.ProjectType, task.Language, task.Branch)
	log.Printf("[Build#%d]   git镜像=%s 仓库=%s 凭据=%s", task.BuildID, task.Steps.GitDockerImage, maskGitURL(task.Steps.GitURL), credType)
	log.Printf("[Build#%d]   构建镜像=%s 构建命令=%q", task.BuildID, task.Steps.BuildDockerImage, task.Steps.BuildCommand)
	log.Printf("[Build#%d]   服务目录=%v 产物目录=%s Dockerfile=%dB 镜像空间=%s/%s Tag=%s", task.BuildID, task.Steps.ArtifactDirs, task.Steps.ArtifactDir, len(task.Steps.DockerfileContent), task.Harbor.URL, strings.ToLower(task.ProjectEnv), task.Steps.ImageTag)
	log.Printf("[Build#%d]   Harbor=%s 用户=%s", task.BuildID, task.Harbor.URL, task.Harbor.User)
}

// ─── Step 1: Git Clone（Docker 容器化）────────────────────────────

func execGitClone(runner *buildRunner, logger *stepLogger, task *BuildTask, codeDir string) error {
	cloneURL := buildCloneURL(task)
	gitImage := task.Steps.GitDockerImage
	if gitImage == "" {
		gitImage = "alpine/git:latest"
	}

	// 构建 docker run 参数：--entrypoint git 保证无论镜像默认入口是什么都能正确执行 git
	args := []string{
		"run", "--rm",
		"--entrypoint", "git",
		"-v", codeDir + ":/workspace",
		"-e", "GIT_TERMINAL_PROMPT=0",
		"-e", "GIT_SSL_NO_VERIFY=true",
	}

	// SSH 凭据：私钥写入独立临时目录（不放 buildDir，避免 clone 目标目录非空导致失败），挂载进容器
	if task.Steps.GitCredential != nil && task.Steps.GitCredential.Type == "ssh_key" {
		keyPath, cleanupKey := writeDeployKey(task)
		defer cleanupKey()
		if keyPath != "" {
			args = append(args, "-v", keyPath+":/tmp/deploy_key:ro")
			args = append(args, "-e", "GIT_SSH_COMMAND=ssh -i /tmp/deploy_key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null")
			logger.log("  凭据类型: ssh_key（已生成临时私钥并挂载）")
		} else {
			logger.log("  [WARN] ssh_key 凭据写入临时文件失败，将以无凭据方式尝试")
		}
	} else if task.Steps.GitCredential != nil {
		logger.log(fmt.Sprintf("  凭据类型: %s", task.Steps.GitCredential.Type))
	}

	args = append(args, gitImage)
	args = append(args, "clone", "--depth", "1", "-b", task.Branch, cloneURL, "/workspace")

	// 日志脱敏：不输出内嵌凭据的 cloneURL
	logger.log(fmt.Sprintf("  镜像: %s", gitImage))
	logger.log(fmt.Sprintf("  拉取: %s (分支: %s)", maskGitURL(cloneURL), task.Branch))
	if err := runner.runCmd(logger, codeDir, "docker", args...); err != nil {
		return err
	}

	// clone 成功后输出最近提交信息（hash/作者/日期/提交信息），best-effort 不影响构建
	logger.log("\n  --- 最近提交 ---")
	logArgs := []string{
		"run", "--rm",
		"--entrypoint", "git",
		"-v", codeDir + ":/workspace",
		"-w", "/workspace",
		gitImage,
		"log", "-1",
		"--date=format:%Y-%m-%d %H:%M:%S",
		"--pretty=format:  提交: %h%n  作者: %an <%ae>%n  日期: %ad%n  信息: %s",
	}
	if err := runner.runCmd(logger, codeDir, "docker", logArgs...); err != nil {
		logger.log("  [WARN] 读取提交信息失败: " + err.Error())
	}
	return nil
}

// ─── Step 2: 编译构建（Docker 容器化）────────────────────────────

func execBuild(runner *buildRunner, logger *stepLogger, task *BuildTask, codeDir string) error {
	buildImage := task.Steps.BuildDockerImage
	if buildImage == "" {
		// 无镜像则直接在宿主机执行（兼容）
		parts := strings.Fields(task.Steps.BuildCommand)
		if len(parts) == 0 {
			return nil
		}
		return runner.runCmd(logger, codeDir, parts[0], parts[1:]...)
	}

	// m2 仓库缓存持久化：{WorkDir}/.m2 挂载到容器 /root/.m2，
	// 避免每次编译重新下载依赖（跨项目/环境共享，构建目录清理不影响缓存）
	m2CacheDir := filepath.Join(cfg.WorkDir, ".m2")
	if err := os.MkdirAll(m2CacheDir, 0755); err != nil {
		logger.log(fmt.Sprintf("  [WARN] 创建m2缓存目录失败(不影响构建): %v", err))
	}

	args := []string{
		"run", "--rm",
		"-v", codeDir + ":/workspace",
		"-v", m2CacheDir + ":/root/.m2",
		"-w", "/workspace",
		buildImage,
		"sh", "-c", task.Steps.BuildCommand,
	}

	logger.log(fmt.Sprintf("  执行: docker %s", strings.Join(args, " ")))
	return runner.runCmd(logger, codeDir, "docker", args...)
}

// ─── Step 3: 产物收集 ─────────────────────────────────────────────

func execCollectArtifacts(logger *stepLogger, task *BuildTask, codeDir, productDir string) error {
	absCode, _ := filepath.Abs(codeDir)
	absProduct, _ := filepath.Abs(productDir)
	logger.log(fmt.Sprintf("  代码目录: %s", absCode))
	logger.log(fmt.Sprintf("  产物根目录: %s", absProduct))

	// 前端：固定收集 dist 目录
	if task.ProjectType == "frontend" {
		if err := collectOne(logger, codeDir, productDir, "dist", ""); err != nil {
			return err
		}
		logger.log("  产物收集完成，共 1 个目录")
		return nil
	}

	// 后端：服务目录列表 + 各服务统一的产物子目录
	svcDirs := task.Steps.ArtifactDirs
	if len(svcDirs) == 0 {
		return fmt.Errorf("未配置服务目录")
	}
	artifactSub := strings.TrimSpace(task.Steps.ArtifactDir)
	for _, svc := range svcDirs {
		if err := collectOne(logger, codeDir, productDir, svc, artifactSub); err != nil {
			return err
		}
	}
	logger.log(fmt.Sprintf("  产物收集完成，共 %d 个服务", len(svcDirs)))
	return nil
}

// collectOne 收集单个服务的产物到 product 下（均按 basename 扁平化）：
//
//	artifactSub 非空：src = codeDir/svcDir/artifactSub → dst = productDir/basename(svcDir)/basename(artifactSub)
//	artifactSub 为空：src = codeDir/svcDir → dst = productDir/basename(svcDir)（兼容旧配置，整个服务目录复制）
func collectOne(logger *stepLogger, codeDir, productDir, svcDir, artifactSub string) error {
	cleanSvc := filepath.Clean(svcDir)
	if filepath.IsAbs(cleanSvc) || strings.HasPrefix(cleanSvc, "..") {
		return fmt.Errorf("服务目录不合法(禁止绝对路径或..): %s", svcDir)
	}

	src := filepath.Join(codeDir, cleanSvc)
	dst := filepath.Join(productDir, filepath.Base(cleanSvc))
	relDesc := cleanSvc
	if artifactSub != "" {
		cleanSub := filepath.Clean(artifactSub)
		if filepath.IsAbs(cleanSub) || strings.HasPrefix(cleanSub, "..") {
			return fmt.Errorf("产物目录不合法(禁止绝对路径或..): %s", artifactSub)
		}
		src = filepath.Join(src, cleanSub)
		dst = filepath.Join(dst, filepath.Base(cleanSub))
		relDesc = cleanSvc + "/" + cleanSub
	}

	// 二次验证：解析后的路径必须在 codeDir 内
	absSrc, _ := filepath.Abs(src)
	absBase, _ := filepath.Abs(codeDir)
	if !strings.HasPrefix(absSrc, absBase+string(os.PathSeparator)) {
		return fmt.Errorf("产物路径逃逸代码目录: %s", relDesc)
	}
	if _, err := os.Stat(src); os.IsNotExist(err) {
		return fmt.Errorf("产物目录不存在: %s (完整路径: %s)", relDesc, absSrc)
	}

	absDst, _ := filepath.Abs(dst)
	relDst, _ := filepath.Rel(productDir, dst)
	logger.log(fmt.Sprintf("  收集: %s → product/%s", relDesc, filepath.ToSlash(relDst)))
	logger.log(fmt.Sprintf("    cp -r %s %s", absSrc, absDst))
	if err := copyDir(src, dst); err != nil {
		return fmt.Errorf("复制产物失败 %s: %v", relDesc, err)
	}
	return nil
}

// ─── Step 4: Docker Build（多线程）────────────────────────────────

func execDockerBuild(runner *buildRunner, logger *stepLogger, task *BuildTask, productDir string) ([]string, error) {
	entries, err := os.ReadDir(productDir)
	if err != nil {
		return nil, fmt.Errorf("读取产物目录失败: %v", err)
	}

	var images []string
	var mu sync.Mutex
	var wg sync.WaitGroup
	var buildErr error

	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		svcName := entry.Name()
		svcPath := filepath.Join(productDir, svcName)
		// 镜像名规范：{harbor}/{project}-{env}/{svcName}:{tag}（命名空间取 ProjectEnv，Docker 要求小写）
		fullImage := fmt.Sprintf("%s/%s:%s", task.Harbor.URL, strings.ToLower(task.ProjectEnv+"/"+svcName), task.Steps.ImageTag)

		wg.Add(1)
		go func(svc, path, img string) {
			defer wg.Done()
			logger.log(fmt.Sprintf("  [并发] 构建镜像: %s", img))

			// 写入 Dockerfile（模板保留 {{jar_name}} / {{jar_path}} / {{workdir}} 占位符，逐服务识别后替换）
			dfPath := filepath.Join(path, "Dockerfile")
			if task.Steps.DockerfileContent != "" {
				content := task.Steps.DockerfileContent
				if strings.Contains(content, "{{jar_name}}") || strings.Contains(content, "{{jar_path}}") {
					jarRel := detectJar(path, task.Steps.ArtifactDir)
					if jarRel == "" {
						mu.Lock()
						if buildErr == nil {
							buildErr = fmt.Errorf("服务 %s 未在产物目录找到可构建的 jar", svc)
						}
						mu.Unlock()
						return
					}
					// jarRel 为相对构建上下文的路径（如 pkg/ysh-gateway.jar）；jarBase 取含扩展名的真实文件名（ysh-gateway.jar），
					// 模板直接以 {{jar_name}} 引用（不再追加 .jar），避免拼出 ysh-gateway.jar.jar
					jarBase := jarRel
					if idx := strings.LastIndex(jarRel, "/"); idx >= 0 {
						jarBase = jarRel[idx+1:]
					}
					logger.log(fmt.Sprintf("  [识别] %s 主 jar: %s", svc, jarRel))
					content = strings.ReplaceAll(content, "{{jar_path}}", jarRel)
					content = strings.ReplaceAll(content, "{{jar_name}}", jarBase)
				}
				// {{workdir}} 替换为服务名，不受 jar 条件限制
				content = strings.ReplaceAll(content, "{{workdir}}", svc)
				os.WriteFile(dfPath, []byte(content), 0644)
			}

			if err := runner.runCmd(logger, path, "docker", "build", "-t", img, "."); err != nil {
				mu.Lock()
				if buildErr == nil {
					buildErr = fmt.Errorf("构建 %s 失败: %v", svc, err)
				}
				mu.Unlock()
				return
			}
			mu.Lock()
			images = append(images, img)
			mu.Unlock()
			logger.log(fmt.Sprintf("  [完成] %s", img))
		}(svcName, svcPath, fullImage)
	}

	wg.Wait()
	if buildErr != nil {
		return nil, buildErr
	}
	return images, nil
}

// detectJar 在服务的构建上下文目录中识别待启动的主 jar，返回相对 svcPath 的斜杠路径。
// 产物已按 artifactDir 扁平化收集到 svcPath/<产物目录basename>/ 下，主 jar 直接位于该目录，
// 故优先非递归扫描该目录（不深入 lib/resource 等子目录）；仅未指定产物目录的旧配置才递归兑底。
func detectJar(svcPath, artifactDir string) string {
	jarDir := svcPath
	if sub := strings.TrimSpace(artifactDir); sub != "" {
		jarDir = filepath.Join(svcPath, filepath.Base(filepath.Clean(sub)))
	}
	if rel := scanJars(svcPath, jarDir, false); rel != "" {
		return rel
	}
	// 兑底：旧配置（未指定产物目录，整个服务目录被复制）时递归查找
	return scanJars(svcPath, svcPath, true)
}

// scanJars 扫描 dir 下的 *.jar（recursive 控制是否递归），过滤 sources/javadoc/original，
// 多个候选取体积最大者（Spring Boot fat jar 通常最大），返回相对 base 的斜杠路径；无则返回 ""。
func scanJars(base, dir string, recursive bool) string {
	var candidates []string
	if recursive {
		filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
			if err == nil && info != nil && !info.IsDir() && isMainJar(info.Name()) {
				candidates = append(candidates, p)
			}
			return nil
		})
	} else {
		entries, err := os.ReadDir(dir)
		if err != nil {
			return ""
		}
		for _, e := range entries {
			if !e.IsDir() && isMainJar(e.Name()) {
				candidates = append(candidates, filepath.Join(dir, e.Name()))
			}
		}
	}
	if len(candidates) == 0 {
		return ""
	}
	best := candidates[0]
	var bestSize int64 = -1
	for _, c := range candidates {
		if fi, err := os.Stat(c); err == nil && fi.Size() > bestSize {
			bestSize = fi.Size()
			best = c
		}
	}
	rel, err := filepath.Rel(base, best)
	if err != nil {
		return ""
	}
	return filepath.ToSlash(rel)
}

// isMainJar 判断文件是否可作为启动 jar（排除源码包/文档包/shade 原始包）
func isMainJar(name string) bool {
	lower := strings.ToLower(name)
	if !strings.HasSuffix(lower, ".jar") {
		return false
	}
	for _, skip := range []string{"sources", "javadoc", "original"} {
		if strings.Contains(lower, skip) {
			return false
		}
	}
	return true
}

// ─── Step 5: Docker Push（并发）───────────────────────────────────

func execDockerPush(runner *buildRunner, logger *stepLogger, task *BuildTask, images []string) error {
	// docker login
	if task.Harbor.Pass != "" {
		if err := dockerLogin(logger, task.Harbor); err != nil {
			return fmt.Errorf("docker login 失败: %v", err)
		}
	}

	var mu sync.Mutex
	var wg sync.WaitGroup
	var pushErr error

	for _, img := range images {
		wg.Add(1)
		go func(image string) {
			defer wg.Done()
			logger.log(fmt.Sprintf("  [并发] 推送: %s", image))
			if err := runner.runCmd(logger, "", "docker", "push", image); err != nil {
				mu.Lock()
				if pushErr == nil {
					pushErr = fmt.Errorf("推送 %s 失败: %v", image, err)
				}
				mu.Unlock()
				return
			}
			logger.log(fmt.Sprintf("  [完成] %s", image))
		}(img)
	}

	wg.Wait()
	return pushErr
}

// ─── 工具函数 ─────────────────────────────────────────────────────

func sshToHTTPS(gitURL string) string {
	// git@host:group/project.git → https://host/group/project.git
	if strings.HasPrefix(gitURL, "git@") {
		rest := strings.TrimPrefix(gitURL, "git@")
		if idx := strings.Index(rest, ":"); idx > 0 {
			host := rest[:idx]
			path := rest[idx+1:]
			return fmt.Sprintf("https://%s/%s", host, path)
		}
	}
	// ssh://git@host:port/group/project.git → https://host/group/project.git
	if strings.HasPrefix(gitURL, "ssh://git@") {
		rest := strings.TrimPrefix(gitURL, "ssh://git@")
		if slashIdx := strings.Index(rest, "/"); slashIdx > 0 {
			hostPart := rest[:slashIdx]
			path := rest[slashIdx+1:]
			if colonIdx := strings.Index(hostPart, ":"); colonIdx > 0 {
				hostPart = hostPart[:colonIdx]
			}
			return fmt.Sprintf("https://%s/%s", hostPart, path)
		}
	}
	return gitURL
}

func buildCloneURL(task *BuildTask) string {
	cred := task.Steps.GitCredential
	gitURL := task.Steps.GitURL

	// ssh_key 类型：保持原 SSH 地址
	if cred != nil && cred.Type == "ssh_key" {
		return gitURL
	}
	cloneURL := sshToHTTPS(gitURL)
	if cred == nil || cred.Secret == "" {
		return cloneURL
	}
	switch cred.Type {
	case "token":
		return strings.Replace(cloneURL, "https://", fmt.Sprintf("https://%s@", cred.Secret), 1)
	case "password":
		return strings.Replace(cloneURL, "https://", fmt.Sprintf("https://%s:%s@", cred.Username, cred.Secret), 1)
	default:
		return cloneURL
	}
}

// writeDeployKey 将 ssh_key 凭据写入独立临时目录（0600），返回密钥路径与清理函数。
// 密钥不放入 buildDir，避免 git clone 目标目录（/workspace）非空而拒绝克隆。
func writeDeployKey(task *BuildTask) (string, func()) {
	noop := func() {}
	cred := task.Steps.GitCredential
	if cred == nil || cred.Type != "ssh_key" || cred.Secret == "" {
		return "", noop
	}
	tmpDir, err := os.MkdirTemp("", "git_deploy_key_*")
	if err != nil {
		return "", noop
	}
	keyPath := filepath.Join(tmpDir, "id_rsa")
	content := cred.Secret
	if !strings.HasSuffix(content, "\n") {
		content += "\n"
	}
	if err := os.WriteFile(keyPath, []byte(content), 0600); err != nil {
		os.RemoveAll(tmpDir)
		return "", noop
	}
	return keyPath, func() { os.RemoveAll(tmpDir) }
}

// maskGitURL 脱敏：将 https://user:pass@host/... 中的凭据替换为 ***
func maskGitURL(u string) string {
	if idx := strings.Index(u, "://"); idx > 0 {
		rest := u[idx+3:]
		if atIdx := strings.Index(rest, "@"); atIdx > 0 {
			return u[:idx+3] + "***@" + rest[atIdx+1:]
		}
	}
	return u
}

// copyDir 递归复制目录（带路径安全校验）
func copyDir(src, dst string) error {
	absDst, _ := filepath.Abs(dst)
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		relPath, _ := filepath.Rel(src, path)
		// 安全检查：确保目标路径不会逃逸 dst
		cleanRel := filepath.Clean(relPath)
		if strings.HasPrefix(cleanRel, "..") {
			return fmt.Errorf("路径不合法: %s", relPath)
		}
		dstPath := filepath.Join(absDst, cleanRel)
		if !strings.HasPrefix(dstPath, absDst+string(os.PathSeparator)) && dstPath != absDst {
			return fmt.Errorf("路径逃逸: %s", relPath)
		}

		if info.IsDir() {
			return os.MkdirAll(dstPath, info.Mode())
		}
		return copyFile(path, dstPath)
	})
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}

// ─── Docker 镜像清理（构建前执行）──────────────────────────────

// execCleanupImages 清理当前项目环境的所有旧 Docker 镜像，保留最新一个
// 非致命：清理失败不影响构建流程
func execCleanupImages(runner *buildRunner, logger *stepLogger, task *BuildTask) {
	if task.Harbor.URL == "" {
		return
	}
	// 过滤：{harbor_url}/{project_env}/*
	imageFilter := fmt.Sprintf("%s/%s/*", task.Harbor.URL, strings.ToLower(task.ProjectEnv))
	logger.log(fmt.Sprintf("\n=== 清理旧镜像 ===\n过滤: %s\n", imageFilter))

	// 获取所有匹配的镜像 ID（按创建时间排序，-q 只返回 ID）
	cmd := exec.Command("docker", "images", "--filter", "reference="+imageFilter, "-q")
	output, err := cmd.Output()
	if err != nil {
		logger.log(fmt.Sprintf("查询旧镜像失败（跳过清理）: %v", err))
		return
	}
	ids := strings.Fields(string(output))
	if len(ids) == 0 {
		logger.log("无旧镜像需清理")
		return
	}

	// 保留最后一个（最新构建的），删除其余
	keep := 1
	if keep >= len(ids) {
		keep = 0
	}
	removeIDs := ids[:len(ids)-keep]

	logger.log(fmt.Sprintf("发现 %d 个旧镜像，保留 %d 个，删除 %d 个", len(ids), keep, len(removeIDs)))

	if len(removeIDs) == 0 {
		return
	}

	// 分批删除（避免参数过长）
	batchSize := 10
	for i := 0; i < len(removeIDs); i += batchSize {
		end := i + batchSize
		if end > len(removeIDs) {
			end = len(removeIDs)
		}
		batch := removeIDs[i:end]
		args := append([]string{"rmi", "-f"}, batch...)
		rmiCmd := exec.Command("docker", args...)
		runner.register(rmiCmd, "")
		if out, err := rmiCmd.CombinedOutput(); err != nil {
			logger.log(fmt.Sprintf("删除批次 %d-%d 部分失败: %v\n%s", i+1, end, err, string(out)))
		}
		runner.unregister(rmiCmd)
	}
	logger.log(fmt.Sprintf("清理完成: 删除了 %d 个旧镜像", len(removeIDs)))
}

// AgentVersion Agent 版本号，编译时可通过 -ldflags -X main.agentVersion=v1.0.0 覆盖
var agentVersion = "v1.0.0"

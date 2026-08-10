package main

// ─── 命令执行 + 步骤日志写入器 ───────────────────────────────────

import (
	"bufio"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
)

// ─── 步骤日志写入器（单文件 build.log，步骤以标签分隔）──────────────

type stepLogger struct {
	mu   sync.Mutex
	file *os.File
}

func newStepLogger(logDir string) *stepLogger {
	path := filepath.Join(logDir, "build.log")
	f, _ := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	return &stepLogger{file: f}
}

func (l *stepLogger) log(line string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		l.file.WriteString(line + "\n")
	}
}

func (l *stepLogger) close() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		l.file.Close()
		l.file = nil
	}
}

// ─── 命令执行（实时捕获输出到本地日志）────────────────────────────

func (r *buildRunner) runCmd(logger *stepLogger, dir, name string, args ...string) error {
	return r.runCmdWithEnv(logger, dir, nil, name, args...)
}

func (r *buildRunner) runCmdWithEnv(logger *stepLogger, dir string, extraEnv []string, name string, args ...string) error {
	// docker run 容器自动注入唯一容器名，便于取消时 docker stop 即时终止（仅杀客户端进程不会停止容器）
	container := ""
	if name == "docker" && len(args) > 0 && args[0] == "run" {
		container = r.nextContainerName()
		named := make([]string, 0, len(args)+2)
		named = append(named, "run", "--name", container)
		named = append(named, args[1:]...)
		args = named
	}

	cmd := exec.Command(name, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0", "GIT_SSL_NO_VERIFY=true")
	cmd.Env = append(cmd.Env, extraEnv...)

	stdout, _ := cmd.StdoutPipe()
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		return err
	}
	r.register(cmd, container)
	defer r.unregister(cmd)

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		logger.log("  " + scanner.Text())
	}

	err := cmd.Wait()
	if r.isKilled() {
		return errBuildCancelled
	}
	return err
}

func dockerLogin(logger *stepLogger, h HarborCfg) error {
	cmd := exec.Command("docker", "login", h.URL, "-u", h.User, "--password-stdin")
	cmd.Stdin = strings.NewReader(h.Pass)
	out, err := cmd.CombinedOutput()
	if err != nil {
		logger.log("  " + string(out))
	}
	return err
}

func getImageDigest(image string) string {
	out, err := exec.Command("docker", "inspect", "--format", "{{index .RepoDigests 0}}", image).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func checkDocker() bool {
	// 优先用绝对路径，兼容 systemd 精简 PATH
	dockerBin := "/usr/bin/docker"
	if _, err := os.Stat(dockerBin); err != nil {
		dockerBin = "docker"
	}
	return exec.Command(dockerBin, "info").Run() == nil
}

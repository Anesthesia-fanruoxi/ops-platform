package main

// ─── 构建取消控制器（即时终止：docker stop 命名容器 + 杀进程）─────────
//
// 设计：整个构建跑在子协程（executeBuild）中，所有外部命令经 buildRunner 登记。
// Master 取消时主动推送 /cancel，handleCancel 找到对应 runner 调 kill()，
// 立即停止当前正在运行的命令，而非等待当前步骤自然结束。

import (
	"fmt"
	"os/exec"
	"sync"
	"time"
)

// errBuildCancelled 哨兵错误：命令因取消被终止
var errBuildCancelled = fmt.Errorf("构建已取消")

// buildRunner 承载单次构建的可取消执行：登记运行中的命令/容器，收到取消信号即终止
type buildRunner struct {
	buildID int

	mu     sync.Mutex
	killed bool
	ops    map[*exec.Cmd]string // 正在运行的命令 -> 容器名（无容器为 ""）
}

func newBuildRunner(buildID int) *buildRunner {
	return &buildRunner{buildID: buildID, ops: make(map[*exec.Cmd]string)}
}

// register 登记运行中的命令（容器名可空）；若已取消则注册即终止
func (r *buildRunner) register(cmd *exec.Cmd, container string) {
	r.mu.Lock()
	if r.killed {
		r.mu.Unlock()
		stopOp(cmd, container)
		return
	}
	r.ops[cmd] = container
	r.mu.Unlock()
}

func (r *buildRunner) unregister(cmd *exec.Cmd) {
	r.mu.Lock()
	delete(r.ops, cmd)
	r.mu.Unlock()
}

func (r *buildRunner) isKilled() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.killed
}

// kill 终止当前构建所有运行中的命令（幂等）
func (r *buildRunner) kill() {
	r.mu.Lock()
	if r.killed {
		r.mu.Unlock()
		return
	}
	r.killed = true
	ops := r.ops
	r.ops = make(map[*exec.Cmd]string)
	r.mu.Unlock()

	for cmd, container := range ops {
		stopOp(cmd, container)
	}
}

// nextContainerName 生成唯一容器名（时间戳避免重跑/并发碰撞），供取消时 docker stop 定位
func (r *buildRunner) nextContainerName() string {
	return fmt.Sprintf("cicd_%d_%d", r.buildID, time.Now().UnixNano())
}

// stopOp 终止单个命令：命名容器先 docker stop（仅杀客户端进程不会停止容器），再杀进程
func stopOp(cmd *exec.Cmd, container string) {
	if container != "" {
		exec.Command("docker", "stop", container).Run()
	}
	if cmd != nil && cmd.Process != nil {
		cmd.Process.Kill()
	}
}

// ─── 全局构建运行器注册表（供 /cancel 推送定位对应 runner）──────────

var (
	runnersMu sync.Mutex
	runners   = map[int]*buildRunner{}
)

func registerRunner(r *buildRunner) {
	runnersMu.Lock()
	runners[r.buildID] = r
	runnersMu.Unlock()
}

func unregisterRunner(r *buildRunner) {
	runnersMu.Lock()
	delete(runners, r.buildID)
	runnersMu.Unlock()
}

func getRunner(buildID int) *buildRunner {
	runnersMu.Lock()
	defer runnersMu.Unlock()
	return runners[buildID]
}

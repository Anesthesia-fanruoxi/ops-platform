package main

// ─── HTTP 服务（任务接收 + 日志查询）──────────────────────────────

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"
)

// runningCount 当前运行中的构建任务数（信号量占用即运行中），心跳上报 Master 作为并发依据
var runningCount int32

func startLogServer() {
	mux := http.NewServeMux()
	mux.HandleFunc("/logs", handleLogs)
	mux.HandleFunc("/agentlog", handleAgentLog)
	mux.HandleFunc("/task", handleTask)
	mux.HandleFunc("/cancel", handleCancel)
	mux.HandleFunc("/list", handleList)
	mux.HandleFunc("/metrics", handleMetricsHistory)
	addr := fmt.Sprintf(":%d", cfg.LogPort)
	log.Printf("[LogServer] 监听 %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Printf("[LogServer] 启动失败: %v", err)
	}
}

// handleTask 接收 Master 推送的构建任务（加密信封）
func handleTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	data, err := io.ReadAll(r.Body)
	if err != nil {
		writeTaskResp(w, false)
		return
	}
	var task BuildTask
	if err := decryptEnvelope(data, &task); err != nil {
		log.Printf("[Task] 解密任务失败: %v", err)
		writeTaskResp(w, false)
		return
	}
	// 并发保护：无空闲槽则拒绝（Master 不应超发，此处兜底）
	select {
	case sem <- struct{}{}:
		atomic.AddInt32(&runningCount, 1)
	default:
		log.Printf("[Task] 并发已满，拒绝构建#%d", task.BuildID)
		writeTaskResp(w, false)
		return
	}
	wg.Add(1)
	go func(t *BuildTask) {
		defer wg.Done()
		defer func() { <-sem }()
		defer atomic.AddInt32(&runningCount, -1)
		executeBuild(t)
	}(&task)
	log.Printf("[Task] 接受构建任务 #%d 项目环境=%s branch=%s", task.BuildID, task.ProjectEnv, task.Branch)
	writeTaskResp(w, true)
}

// handleCancel 接收 Master 主动推送的取消信号（加密信封），即时终止当前运行的构建操作
func handleCancel(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	data, err := io.ReadAll(r.Body)
	if err != nil {
		writeTaskResp(w, false)
		return
	}
	var req struct {
		BuildID int `json:"build_id"`
	}
	if err := decryptEnvelope(data, &req); err != nil || req.BuildID == 0 {
		writeTaskResp(w, false)
		return
	}
	if runner := getRunner(req.BuildID); runner != nil {
		log.Printf("[Cancel] 构建#%d 收到取消信号，终止当前运行操作", req.BuildID)
		// 异步 kill：docker stop 有 10s 宽限期，同步等待会超过 Master 推送超时（5s）被误记推送失败
		go runner.kill()
		writeTaskResp(w, true)
	} else {
		// 构建未在运行（不存在/已完成）：如实上报失败，避免 Master 误以为已取消
		log.Printf("[Cancel] 构建#%d 未找到运行中任务，取消失败", req.BuildID)
		writeTaskResp(w, false)
	}
}

// writeTaskResp 以加密信封响应 Master
func writeTaskResp(w http.ResponseWriter, ok bool) {
	resp, err := encryptEnvelope(map[string]interface{}{"ok": ok})
	if err != nil {
		http.Error(w, "encrypt failed", 500)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(resp)
}

// handleAgentLog 读取 Agent 自身运行日志（{WorkDir}/logs/agent.log，main.go 双写落盘），
// 复用 streamBuildLog 的全文 tail 逻辑（marker 为空 = 全文），支持 follow 流式
func handleAgentLog(w http.ResponseWriter, r *http.Request) {
	follow := r.URL.Query().Get("follow") == "true"
	logPath := filepath.Join(cfg.WorkDir, "logs", "agent.log")
	streamBuildLog(w, r, logPath, "", follow)
}

// stepMarkers 日志类型 → 单文件 build.log 中的步骤标签（用于定位起始位置）
var stepMarkers = map[string]string{
	"git":     "=== Git Clone ===",
	"mvn":     "=== 编译构建 ===",
	"product": "=== 产物收集 ===",
	"build":   "=== Docker Build ===",
	"push":    "=== Docker Push ===",
}

// stepOrder 步骤标签顺序，用于确定某步骤的结束边界（下一个标签的起始位置）
var stepOrder = []string{"=== Git Clone ===", "=== 编译构建 ===", "=== 产物收集 ===", "=== Docker Build ===", "=== Docker Push ==="}

func handleLogs(w http.ResponseWriter, r *http.Request) {
	projectEnv := r.URL.Query().Get("project_env")
	buildNo := r.URL.Query().Get("build_no")
	logType := r.URL.Query().Get("type")
	follow := r.URL.Query().Get("follow") == "true"

	if projectEnv == "" {
		http.Error(w, "project_env required", 400)
		return
	}
	if buildNo == "" {
		http.Error(w, "build_no required", 400)
		return
	}
	// 防止路径遍历：project_env / build_no 只允许字母数字和下划线、连字符
	for _, c := range projectEnv {
		if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-') {
			http.Error(w, "invalid project_env", 400)
			return
		}
	}
	for _, c := range buildNo {
		if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-') {
			http.Error(w, "invalid build_no", 400)
			return
		}
	}

	// 确定步骤标签（all 为空 = 全文）
	var marker string
	if logType != "all" {
		m, ok := stepMarkers[logType]
		if !ok {
			http.Error(w, "invalid type (all/git/mvn/product/build/push)", 400)
			return
		}
		marker = m
	}

	logPath := filepath.Join(cfg.WorkDir, projectEnv, buildNo, "logs", "build.log")
	streamBuildLog(w, r, logPath, marker, follow)
}

// findSection 在 content 中定位 marker 对应步骤的字节范围 [start, end)
// 起始标签取最后一次出现（重跑时同一步骤会有多个标签，展示最新一次执行）；结束边界取其后最近的其它标签
func findSection(content []byte, marker string) (int, int) {
	idx := strings.LastIndex(string(content), marker)
	if idx < 0 {
		return -1, -1
	}
	// 找下一个步骤标签作为结束边界
	end := len(content)
	for _, m := range stepOrder {
		if m == marker {
			continue
		}
		nextIdx := strings.Index(string(content[idx+len(marker):]), m)
		if nextIdx >= 0 {
			pos := idx + len(marker) + nextIdx
			if pos < end {
				end = pos
			}
		}
	}
	return idx, end
}

// sseEscape 转义日志内容为 SSE 单行 data：去除 \r（SSE 协议中 \r 也是行终止符，会导致事件碎裂），\n 替换为字面量 \\n
func sseEscape(b []byte) string {
	s := strings.ReplaceAll(string(b), "\r", "")
	return strings.ReplaceAll(s, "\n", "\\n")
}

// streamBuildLog 单文件日志流：marker 为空时输出全文（总览），否则只输出对应步骤标签区间
func streamBuildLog(w http.ResponseWriter, r *http.Request, path, marker string, follow bool) {
	if follow {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming not supported", 500)
			return
		}

		// 立即发送初始心跳，避免 Master 代理 / 浏览器 EventSource pending
		fmt.Fprintf(w, ": connected\n\n")
		flusher.Flush()

		var offset int64

		// 立即读取已有内容（历史日志秒出）
		data, _ := os.ReadFile(path)
		if len(data) > 0 {
			if marker == "" {
				fmt.Fprintf(w, "data: %s\n\n", sseEscape(data))
				offset = int64(len(data))
			} else {
				start, end := findSection(data, marker)
				if start >= 0 {
					fmt.Fprintf(w, "data: %s\n\n", sseEscape(data[start:end]))
					offset = int64(end)
				}
			}
			flusher.Flush()
		}

		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		timeout := time.After(5 * time.Minute)
		heartbeat := time.NewTicker(15 * time.Second)
		defer heartbeat.Stop()

		for {
			select {
			case <-timeout:
				return
			case <-r.Context().Done():
				return
			case <-heartbeat.C:
				fmt.Fprintf(w, ": keepalive\n\n")
				flusher.Flush()
			case <-ticker.C:
				data, err := os.ReadFile(path)
				if err != nil {
					continue
				}
				if marker == "" {
					// 总览：从 offset 追加
					if int64(len(data)) > offset {
						chunk := data[offset:]
						fmt.Fprintf(w, "data: %s\n\n", sseEscape(chunk))
						offset = int64(len(data))
						flusher.Flush()
					}
				} else {
					// 步骤模式：重新定位区间，发送增量
					start, end := findSection(data, marker)
					if start >= 0 && int64(end) > offset {
						if offset < int64(start) {
							offset = int64(start)
						}
						chunk := data[offset:end]
						fmt.Fprintf(w, "data: %s\n\n", sseEscape(chunk))
						offset = int64(end)
						flusher.Flush()
					}
				}
			}
		}
	} else {
		// 一次性返回
		data, _ := os.ReadFile(path)
		if marker != "" && len(data) > 0 {
			start, end := findSection(data, marker)
			if start >= 0 {
				data = data[start:end]
			} else {
				data = nil
			}
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.Write(data)
	}
}

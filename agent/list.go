package main

// ─── 工作目录只读列举（防越界：Clean+Join+Abs+EvalSymlinks 双重前缀校验）───

import (
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// handleList 处理 POST /list：解密 {path} → 单层列举工作目录内目录（只读，不返回文件内容）
func handleList(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	data, err := io.ReadAll(r.Body)
	if err != nil {
		writeListResp(w, false, "读取请求体失败", nil)
		return
	}
	var req struct {
		Path string `json:"path"`
	}
	if err := decryptEnvelope(data, &req); err != nil {
		log.Printf("[List] 解密请求失败: %v", err)
		writeListResp(w, false, "报文解密失败", nil)
		return
	}
	entries, errMsg := listWorkDir(req.Path)
	writeListResp(w, errMsg == "", errMsg, entries)
}

// listWorkDir 单层列举工作目录下的相对路径；越界/不存在/非目录返回错误信息
func listWorkDir(path string) ([]map[string]interface{}, string) {
	workAbs, err := filepath.Abs(cfg.WorkDir)
	if err != nil {
		return nil, "工作目录解析失败"
	}
	// 工作目录自身先 EvalSymlinks 归一（Windows 短路径/目录链接场景），保证前缀比较基准一致
	if real, rerr := filepath.EvalSymlinks(workAbs); rerr == nil {
		workAbs = real
	}
	path = strings.TrimSpace(path)
	if path == "" {
		path = "."
	}
	// 拒绝绝对路径与上级目录引用
	if strings.HasPrefix(path, "/") || path == ".." || strings.HasPrefix(path, "../") {
		return nil, "路径越界：不允许绝对路径或上级目录"
	}
	full, err := filepath.Abs(filepath.Join(workAbs, filepath.Clean(path)))
	if err != nil {
		return nil, "路径解析失败"
	}
	// 双重校验：原始解析路径 + EvalSymlinks 真实路径都必须落在工作目录内（防符号链接逃逸）
	if !withinWorkDir(workAbs, full) {
		return nil, "路径越界：目标不在工作目录内"
	}
	if real, rerr := filepath.EvalSymlinks(full); rerr == nil && !withinWorkDir(workAbs, real) {
		return nil, "路径越界：符号链接指向工作目录之外"
	}

	info, err := os.Stat(full)
	if err != nil {
		return nil, "路径不存在或不可访问"
	}
	if !info.IsDir() {
		return nil, "目标不是目录"
	}

	fis, err := os.ReadDir(full)
	if err != nil {
		return nil, "读取目录失败"
	}
	entries := make([]map[string]interface{}, 0, len(fis))
	for _, fe := range fis {
		e := map[string]interface{}{"name": fe.Name(), "type": "unknown", "size": int64(0), "mtime": ""}
		if fi, ferr := fe.Info(); ferr == nil {
			switch {
			case fi.IsDir():
				e["type"] = "dir"
			case fi.Mode()&os.ModeSymlink != 0:
				e["type"] = "link"
			default:
				e["type"] = "file"
			}
			e["size"] = fi.Size()
			e["mtime"] = fi.ModTime().Format("2006-01-02 15:04:05")
		}
		entries = append(entries, e)
	}
	return entries, ""
}

// withinWorkDir 判断 abs 路径是否等于工作目录或在其内部
func withinWorkDir(workAbs, abs string) bool {
	if abs == workAbs {
		return true
	}
	return strings.HasPrefix(abs, workAbs+string(os.PathSeparator))
}

// writeListResp 以加密信封响应目录列举结果
func writeListResp(w http.ResponseWriter, ok bool, errMsg string, entries []map[string]interface{}) {
	resp, err := encryptEnvelope(map[string]interface{}{
		"ok": ok, "error": errMsg, "entries": entries,
	})
	if err != nil {
		http.Error(w, "encrypt failed", 500)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(resp)
}

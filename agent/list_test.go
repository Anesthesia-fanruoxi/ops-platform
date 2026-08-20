package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestListWorkDirBoundaries 越界路径/符号链接逃逸自测（阶段一检查点）
func TestListWorkDirBoundaries(t *testing.T) {
	tmp := t.TempDir()
	cfg.WorkDir = tmp
	os.MkdirAll(filepath.Join(tmp, "p1-e1-backend", "B1", "logs"), 0755)
	os.WriteFile(filepath.Join(tmp, "p1-e1-backend", "B1", "logs", "build.log"), []byte("hi"), 0644)

	cases := []struct {
		path string
		bad  bool
	}{
		{"", false},
		{".", false},
		{"p1-e1-backend", false},
		{"p1-e1-backend/B1", false},
		{"p1-e1-backend/B1/logs", false},
		{"/etc", true},
		{"..", true},
		{"../..", true},
		{"p1-e1-backend/../../etc", true},
		{"p1-e1-backend/../p1-e1-backend", false}, // 归一回落后仍在工作目录内
	}
	for _, c := range cases {
		_, errMsg := listWorkDir(c.path)
		if c.bad && errMsg == "" {
			t.Errorf("path %q 应被拒绝，但未拒绝", c.path)
		}
		if !c.bad && errMsg != "" {
			t.Errorf("path %q 应通过，但被拒: %s", c.path, errMsg)
		}
	}

	// 符号链接逃逸：创建指向工作目录外的链接（Windows 无权限时跳过该用例）
	outside := filepath.Join(os.TempDir(), "agent-list-outside")
	os.RemoveAll(outside)
	os.MkdirAll(outside, 0755)
	linkPath := filepath.Join(tmp, "p1-e1-backend", "escape")
	if err := os.Symlink(outside, linkPath); err == nil {
		_, errMsg := listWorkDir("p1-e1-backend/escape")
		if errMsg == "" {
			t.Error("符号链接指向工作目录外，应被拒绝但未拒绝")
		}
		os.RemoveAll(outside)
	} else {
		t.Log("跳过符号链接用例（当前环境无 Symlink 权限）")
	}

	// 正常列举内容校验
	entries, errMsg := listWorkDir("p1-e1-backend/B1/logs")
	if errMsg != "" || len(entries) != 1 || entries[0]["name"] != "build.log" || entries[0]["type"] != "file" {
		t.Fatalf("列举异常: entries=%v err=%s", entries, errMsg)
	}
}

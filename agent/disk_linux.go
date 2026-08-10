//go:build linux

package main

// ─── 磁盘容量采集（Linux 实现：statfs 工作目录所在文件系统）───
// 构建产物落在该盘，取工作目录所在文件系统最实用。

import "syscall"

// sampleDiskGB 用 statfs 统计工作目录所在文件系统容量（used=true 返回已用 GB）
func sampleDiskGB(used bool) float64 {
	var st syscall.Statfs_t
	if err := syscall.Statfs(cfg.WorkDir, &st); err != nil {
		return 0
	}
	total := float64(st.Blocks) * float64(st.Bsize) / 1024 / 1024 / 1024
	if used {
		avail := float64(st.Bavail) * float64(st.Bsize) / 1024 / 1024 / 1024
		return round1(total - avail)
	}
	return round1(total)
}

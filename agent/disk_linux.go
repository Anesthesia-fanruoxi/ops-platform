//go:build linux

package main

// ─── 磁盘容量采集（Linux 实现：statfs 工作目录所在文件系统）───
// 构建产物落在该盘，取工作目录所在文件系统最实用。

import "syscall"

// sampleDiskGB 用 statfs 统计工作目录所在文件系统容量，返回（总量 GB，已用 GB）
// 已用 = 总量 - Bavail（非特权用户可用空间），与构建进程实际可用空间一致
func sampleDiskGB() (totalGB, usedGB float64) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(cfg.WorkDir, &st); err != nil {
		return 0, 0
	}
	totalGB = round1(float64(st.Blocks) * float64(st.Bsize) / 1024 / 1024 / 1024)
	availGB := float64(st.Bavail) * float64(st.Bsize) / 1024 / 1024 / 1024
	return totalGB, round1(totalGB - availGB)
}

package gomobile

import "github.com/OpenMinis/minis-rclone/publicwatch"

// PublicGet runs on a caller-owned background thread.
func PublicGet(kind, target, url string) string { return publicwatch.Get(kind, target, url) }

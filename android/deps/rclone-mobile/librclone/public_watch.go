package main

import "C"

import "github.com/OpenMinis/minis-rclone/publicwatch"

// NanoMusePublicGET returns a JSON string released with MinisRcloneFreeString.
//
//export NanoMusePublicGET
func NanoMusePublicGET(kind, target, url *C.char) *C.char {
	return C.CString(publicwatch.Get(C.GoString(kind), C.GoString(target), C.GoString(url)))
}

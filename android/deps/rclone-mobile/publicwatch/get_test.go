package publicwatch

import (
	"encoding/json"
	"net/netip"
	"net/url"
	"testing"
)

func TestAddressScope(t *testing.T) {
	for _, s := range []string{"127.0.0.1", "::1", "100.64.0.1", "192.0.2.1", "2001:db8::1", "fd00::1", "0.0.0.0", "169.254.0.1", "2002:a00:1::1", "::ffff:10.0.0.1"} {
		if publicIP(netip.MustParseAddr(s)) {
			t.Errorf("Unexpected address %s", s)
		}
	}
	for _, s := range []string{"1.1.1.1", "2606:4700:4700::1111"} {
		if !publicIP(netip.MustParseAddr(s)) {
			t.Errorf("Public address rejected: %s", s)
		}
	}
}
func TestRequestScope(t *testing.T) {
	for _, v := range []struct {
		kind, target, raw string
		good              bool
	}{
		{"github_repo", "sample/notes", "https://api.github.com/search/issues?q=test", true},
		{"github_user", "sample", "https://api.github.com/user", false},
		{"feed", "https://example.org/feed", "https://example.org/updates/rss.xml", true},
		{"feed", "https://example.org/feed", "https://example.com/feed", false},
		{"feed", "https://example.org/feed", "https://example.org/feed?key=example", false},
		{"research_work", "10.1234/x", "https://api.openalex.org/works/https://doi.org/10.1234/x?select=id,doi", true},
		{"research_topic", "quantum optics", "https://api.openalex.org:8080/works", false},
	} {
		u, _ := url.Parse(v.raw)
		if allowed(v.kind, v.target, u) != v.good {
			t.Errorf("scope mismatch %s", v.raw)
		}
		if !v.good {
			var r map[string]string
			if json.Unmarshal([]byte(Get(v.kind, v.target, v.raw)), &r) != nil || r["error"] == "" {
				t.Fatal("Expected unavailable result")
			}
		}
	}
}

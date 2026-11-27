// Package publicwatch provides the two phones with the same anonymous, bounded HTTPS reader.
package publicwatch

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

var publisherHost = regexp.MustCompile(`^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$`)
var publisherPath = regexp.MustCompile(`^/[A-Za-z0-9._~/-]{0,256}$`)
var excluded = func() []netip.Prefix {
	var p []netip.Prefix
	for _, v := range strings.Fields("0.0.0.0/8 100.64.0.0/10 192.0.0.0/24 192.0.2.0/24 192.88.99.0/24 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 240.0.0.0/4 2001::/23 2001:db8::/32 2002::/16 3fff::/20") {
		p = append(p, netip.MustParsePrefix(v))
	}
	return p
}()
var ipv6Internet = netip.MustParsePrefix("2000::/3")

func publicIP(ip netip.Addr) bool {
	ip = ip.Unmap()
	if !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.Zone() != "" || (ip.Is6() && !ipv6Internet.Contains(ip)) {
		return false
	}
	for _, prefix := range excluded {
		if prefix.Contains(ip) {
			return false
		}
	}
	return true
}

func allowed(kind, target string, u *url.URL) bool {
	if u == nil || u.Scheme != "https" || u.User != nil || u.Fragment != "" || u.Host != u.Hostname() || len(u.String()) > 3000 {
		return false
	}
	switch kind {
	case "github_user", "github_repo":
		return u.Host == "api.github.com" && u.Path == "/search/issues"
	case "research_author", "research_work", "research_topic":
		return u.Host == "api.openalex.org" && (u.Path == "/works" || (kind == "research_work" && strings.HasPrefix(u.Path, "/works/https://doi.org/10.")))
	case "feed":
		origin, err := url.Parse(target)
		if err != nil || origin.Scheme != "https" || origin.User != nil || origin.Host != u.Host || !publisherHost.MatchString(u.Host) || u.RawQuery != "" || u.ForceQuery || !publisherPath.MatchString(u.EscapedPath()) || strings.HasPrefix(u.Path, "//") {
			return false
		}
		for _, s := range []string{".local", ".localhost", ".internal", ".lan", ".home", ".onion"} {
			if strings.HasSuffix(u.Host, s) {
				return false
			}
		}
		for _, seg := range strings.Split(u.Path, "/") {
			if seg == "." || seg == ".." {
				return false
			}
		}
		return true
	}
	return false
}

// read pins the TCP destination after checking every address, while net/http verifies the
// original DNS name for TLS and Host. Neither app cookies nor system proxy credentials are used.
func read(ctx context.Context, kind, target, raw string) (map[string]string, error) {
	u, err := url.Parse(raw)
	if err != nil || !allowed(kind, target, u) {
		return nil, errors.New("unsupported URL")
	}
	host := u.Host
	addresses, err := net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	if err != nil || len(addresses) == 0 {
		return nil, errors.New("unavailable host")
	}
	for _, ip := range addresses {
		if !publicIP(ip) {
			return nil, errors.New("non-public address")
		}
	}
	dialer := net.Dialer{Timeout: 3 * time.Second}
	transport := &http.Transport{DisableCompression: true, DisableKeepAlives: true, MaxResponseHeaderBytes: 65536, TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, ServerName: host}, TLSHandshakeTimeout: 5 * time.Second,
		DialContext: func(ctx context.Context, network, requested string) (net.Conn, error) {
			if requested != net.JoinHostPort(host, "443") {
				return nil, errors.New("unexpected destination")
			}
			for n, ip := range addresses {
				if n >= 3 {
					break
				}
				conn, e := dialer.DialContext(ctx, "tcp", net.JoinHostPort(ip.String(), "443"))
				if e == nil {
					return conn, nil
				}
			}
			return nil, errors.New("cannot connect")
		}}
	defer transport.CloseIdleConnections()
	client := http.Client{Transport: transport, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if kind != "feed" || len(via) > 2 || !allowed(kind, target, r.URL) {
			return errors.New("unexpected redirect")
		}
		r.Header.Del("Referer")
		return nil
	}}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, raw, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "nanoMuse/public-watch")
	req.Header.Set("Accept-Encoding", "identity")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	limit := int64(2 << 20)
	if kind == "feed" {
		limit = 1 << 20
	}
	enc := resp.Header.Get("Content-Encoding")
	if resp.StatusCode != http.StatusOK || (enc != "" && !strings.EqualFold(enc, "identity")) || resp.ContentLength > limit {
		return nil, errors.New("invalid response")
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil || int64(len(body)) > limit || !utf8.Valid(body) || (resp.ContentLength >= 0 && int64(len(body)) != resp.ContentLength) {
		return nil, errors.New("incomplete response")
	}
	return map[string]string{"body": string(body), "finalUrl": resp.Request.URL.String()}, nil
}

// Get returns one UTF-8 JSON document to a native worker. Error details never include an address.
func Get(kind, target, raw string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	result, err := read(ctx, kind, target, raw)
	if err != nil {
		return `{"error":"Public source unavailable"}`
	}
	b, _ := json.Marshal(result)
	return string(b)
}

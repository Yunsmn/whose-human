// Go net/http with its defaults (http.DefaultClient). Over TLS it negotiates HTTP/2 when the
// server offers it, as Borysenko 2026 observed for Antigravity (User-Agent Go-http-client/2.0).
//
// Usage: go run ./nethttp <base_url> <text>
package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"

	"whose-human/baselines/internal/think"
)

func status(resp *http.Response, err error) int {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 0
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	return resp.StatusCode
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: nethttp <base_url> <text>")
		os.Exit(2)
	}
	base, text := os.Args[1], os.Args[2]
	if !strings.HasSuffix(base, "/") {
		base += "/"
	}
	think.Check()
	steps := []struct {
		name string
		do   func() int
	}{
		{"GET index.html", func() int { return status(http.Get(base + "index.html")) }},
		{"GET input.html", func() int { return status(http.Get(base + "input.html")) }},
		{"GET submit", func() int { return status(http.Get(base + "submit?" + url.Values{"text": {text}}.Encode())) }},
		{"POST submit", func() int { return status(http.PostForm(base+"submit", url.Values{"text": {text}})) }},
	}
	codes := make([]int, len(steps))
	for i, step := range steps {
		if i > 0 {
			think.Pause()
		}
		codes[i] = step.do()
	}
	failed := false
	for i, step := range steps {
		fmt.Println(step.name, codes[i])
		if codes[i] != 200 {
			failed = true
		}
	}
	if failed {
		os.Exit(1)
	}
}

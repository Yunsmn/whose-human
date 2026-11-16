// Colly with its defaults (the scraping framework Borysenko 2026 saw from Windsurf). Colly
// refuses to visit the same URL twice and does not follow our links on its own here: the four
// requests are issued explicitly so every stack makes the same visit.
//
// Usage: go run ./colly <base_url> <text>
package main

import (
	"fmt"
	"net/url"
	"os"
	"strings"

	"github.com/gocolly/colly/v2"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: colly <base_url> <text>")
		os.Exit(2)
	}
	base, text := os.Args[1], os.Args[2]
	if !strings.HasSuffix(base, "/") {
		base += "/"
	}

	c := colly.NewCollector()
	codes := map[string]int{}
	c.OnResponse(func(r *colly.Response) { codes[r.Request.Method+" "+r.Request.URL.String()] = r.StatusCode })
	c.OnError(func(r *colly.Response, err error) {
		fmt.Fprintln(os.Stderr, err)
		codes[r.Request.Method+" "+r.Request.URL.String()] = r.StatusCode
	})

	getSubmit := base + "submit?" + url.Values{"text": {text}}.Encode()
	steps := []struct{ name, method, url string }{
		{"GET index.html", "GET", base + "index.html"},
		{"GET input.html", "GET", base + "input.html"},
		{"GET submit", "GET", getSubmit},
		{"POST submit", "POST", base + "submit"},
	}
	for _, step := range steps {
		if step.method == "POST" {
			c.Post(step.url, map[string]string{"text": text})
		} else {
			c.Visit(step.url)
		}
	}

	failed := false
	for _, step := range steps {
		parsed, _ := url.Parse(step.url)
		code := codes[step.method+" "+parsed.String()]
		fmt.Println(step.name, code)
		if code != 200 {
			failed = true
		}
	}
	if failed {
		os.Exit(1)
	}
}

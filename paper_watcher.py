#!/usr/bin/env python3
"""
论文笔记自动化工具
功能：
1. 监控Markdown文件变化
2. 检测新增的论文链接（支持arXiv、DOI）
3. 自动下载PDF
4. 获取论文元数据（标题、作者、引用数）
5. 生成格式化的引用信息
"""

import os
import re
import time
import json
import hashlib
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse, unquote

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
except ImportError:
    print("请安装 watchdog: pip install watchdog")
    exit(1)

# ==================== 配置 ====================
CONFIG = {
    "watch_dir": "./papers",           # 监控的目录
    "pdf_dir": "./papers/pdfs",        # PDF保存目录
    "state_file": ".paper_watcher_state.json",  # 状态文件
    "check_interval": 2,               # 检查间隔（秒）
    # 代理配置（Clash默认端口）
    "proxy": {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897"
    },
    "use_proxy": True,                 # 是否使用代理
}

# ==================== 数据类 ====================

def get_proxies():
    """获取代理配置"""
    if CONFIG.get("use_proxy", False):
        return CONFIG.get("proxy", {})
    return None

@dataclass
class PaperInfo:
    title: str
    authors: List[str]
    venue: str  # 期刊/会议
    year: str
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    pdf_url: Optional[str] = None
    citations: Optional[int] = None
    
    def format_authors(self, max_authors: int = 3) -> str:
        """格式化作者列表"""
        if len(self.authors) <= max_authors:
            return ", ".join(self.authors)
        return f"{', '.join(self.authors[:max_authors])} et al."
    
    def to_markdown(self, local_pdf_path: Optional[str] = None) -> str:
        """生成Markdown格式的引用
        格式: 标题.作者.期刊/会议,年份 ([PDF](链接)) ([arXiv](链接)) (Citations: 数量)
        """
        # 基本信息
        result = f"**{self.title}**. {self.format_authors()}. {self.venue}, {self.year}"
        
        # 链接部分
        links = []
        if local_pdf_path:
            links.append(f"[PDF]({local_pdf_path})")
        if self.arxiv_id:
            links.append(f"[arXiv](https://arxiv.org/abs/{self.arxiv_id})")
        if self.doi:
            links.append(f"[DOI](https://doi.org/{self.doi})")
        
        # 引用数
        citation_str = f"Citations: {self.citations}" if self.citations is not None else "Citations: N/A"
        
        # 组合：每个链接用括号包裹
        if links:
            result += " " + " ".join(f"({link})" for link in links)
        result += f" ({citation_str})"
        
        return result


# ==================== URL解析器 ====================
class URLParser:
    """解析论文URL，提取ID"""
    
    # arXiv URL模式
    ARXIV_PATTERNS = [
        r'arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)',
        r'arxiv\.org/pdf/(\d{4}\.\d{4,5}(?:v\d+)?)',
        r'arxiv\.org/abs/([a-z-]+/\d{7})',
        r'arxiv\.org/pdf/([a-z-]+/\d{7})',
    ]
    
    # DOI URL模式
    DOI_PATTERNS = [
        r'doi\.org/(10\.\d{4,}/[^\s\)]+)',
        r'doi:\s*(10\.\d{4,}/[^\s\)]+)',
    ]
    
    @classmethod
    def extract_arxiv_id(cls, url: str) -> Optional[str]:
        """从URL提取arXiv ID"""
        for pattern in cls.ARXIV_PATTERNS:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                arxiv_id = match.group(1)
                # 去除版本号用于比较
                return arxiv_id.split('v')[0] if 'v' in arxiv_id else arxiv_id
        return None
    
    @classmethod
    def extract_doi(cls, url: str) -> Optional[str]:
        """从URL提取DOI"""
        for pattern in cls.DOI_PATTERNS:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1).rstrip('.')
        return None
    
    @classmethod
    def find_urls_in_text(cls, text: str) -> List[str]:
        """从文本中提取所有URL"""
        url_pattern = r'https?://[^\s\)\]<>\"\']+|doi:\s*10\.\d{4,}/[^\s\)\]<>\"\'"]+'
        urls = re.findall(url_pattern, text)
        return [url.rstrip('.,;:') for url in urls]


# ==================== API客户端 ====================
class ArxivAPI:
    """arXiv API客户端"""
    
    BASE_URL = "https://export.arxiv.org/api/query"
    
    @classmethod
    def get_paper_info(cls, arxiv_id: str) -> Optional[PaperInfo]:
        """通过arXiv ID获取论文信息"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            params = {"id_list": arxiv_id}
            response = requests.get(cls.BASE_URL, params=params, headers=headers, 
                                    proxies=get_proxies(), timeout=30)
            response.raise_for_status()
            
            # 解析XML响应
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.text)
            
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entry = root.find('atom:entry', ns)
            
            if entry is None:
                return None
            
            title = entry.find('atom:title', ns)
            title_text = title.text.strip().replace('\n', ' ') if title is not None else "Unknown"
            
            authors = []
            for author in entry.findall('atom:author', ns):
                name = author.find('atom:name', ns)
                if name is not None:
                    authors.append(name.text)
            
            published = entry.find('atom:published', ns)
            year = published.text[:4] if published is not None else "Unknown"
            
            # 获取分类作为venue
            categories = entry.findall('atom:category', ns)
            primary_category = categories[0].get('term') if categories else "arXiv"
            
            # PDF链接
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            
            return PaperInfo(
                title=title_text,
                authors=authors,
                venue=f"arXiv:{primary_category}",
                year=year,
                arxiv_id=arxiv_id,
                pdf_url=pdf_url
            )
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print(f"  [警告] arXiv API访问受限，尝试使用Semantic Scholar...")
                return cls._fallback_semantic_scholar(arxiv_id)
            print(f"  [错误] 获取arXiv信息失败: {e}")
            return None
        except Exception as e:
            print(f"  [错误] 获取arXiv信息失败: {e}")
            return None
    
    @classmethod
    def _fallback_semantic_scholar(cls, arxiv_id: str) -> Optional[PaperInfo]:
        """使用Semantic Scholar作为备用"""
        return SemanticScholarAPI.get_full_paper_info(arxiv_id)


class SemanticScholarAPI:
    """Semantic Scholar API客户端 - 用于获取论文信息和引用数"""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
    
    @classmethod
    def _request_with_retry(cls, url: str, params: dict, max_retries: int = 3) -> Optional[dict]:
        """带重试机制的请求"""
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers,
                                        proxies=get_proxies(), timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # 被限速，等待后重试
                    wait_time = (attempt + 1) * 3  # 3秒, 6秒, 9秒
                    print(f"  [警告] API限速，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  [警告] API返回: {response.status_code}")
                    return None
            except Exception as e:
                print(f"  [警告] 请求失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
        return None
    
    @classmethod
    def get_citations(cls, arxiv_id: str = None, doi: str = None) -> Optional[int]:
        """获取论文引用数"""
        if arxiv_id:
            paper_id = f"arXiv:{arxiv_id}"
        elif doi:
            paper_id = doi
        else:
            return None
        
        url = f"{cls.BASE_URL}/{paper_id}"
        params = {"fields": "citationCount"}
        
        data = cls._request_with_retry(url, params)
        if data:
            return data.get('citationCount')
        return None
    
    @classmethod
    def get_full_paper_info(cls, arxiv_id: str) -> Optional[PaperInfo]:
        """通过arXiv ID获取完整论文信息"""
        url = f"{cls.BASE_URL}/arXiv:{arxiv_id}"
        params = {"fields": "title,authors,year,venue,citationCount,externalIds,publicationVenue"}
        
        data = cls._request_with_retry(url, params)
        if not data:
            return None
        
        authors = [a.get('name', 'Unknown') for a in data.get('authors', [])]
        
        # 获取venue信息
        venue = data.get('venue') or ''
        pub_venue = data.get('publicationVenue')
        if pub_venue and pub_venue.get('name'):
            venue = pub_venue.get('name')
        if not venue:
            venue = 'arXiv'
        
        return PaperInfo(
            title=data.get('title', 'Unknown'),
            authors=authors,
            venue=venue,
            year=str(data.get('year', 'Unknown')),
            arxiv_id=arxiv_id,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            citations=data.get('citationCount')
        )


# ==================== PDF下载器 ====================
class PDFDownloader:
    """PDF下载器"""
    
    @classmethod
    def download(cls, url: str, save_path: str) -> bool:
        """下载PDF文件"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, proxies=get_proxies(), 
                                    timeout=60, stream=True)
            response.raise_for_status()
            
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            print(f"  [错误] 下载PDF失败: {e}")
            return False
    
    @classmethod
    def generate_filename(cls, paper_info: PaperInfo) -> str:
        """生成安全的文件名"""
        # 清理标题，移除不安全字符
        title = re.sub(r'[<>:"/\\|?*]', '', paper_info.title)
        title = title[:80]  # 限制长度
        first_author = paper_info.authors[0].split()[-1] if paper_info.authors else "Unknown"
        return f"{first_author}_{paper_info.year}_{title}.pdf"


# ==================== 状态管理 ====================
class StateManager:
    """管理已处理的URL状态"""
    
    def __init__(self, state_file: str):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """加载状态文件"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"processed_urls": {}, "file_hashes": {}}
    
    def save_state(self):
        """保存状态"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
    
    def is_url_processed(self, url: str) -> bool:
        """检查URL是否已处理"""
        return url in self.state["processed_urls"]
    
    def mark_url_processed(self, url: str, paper_info: dict):
        """标记URL为已处理"""
        self.state["processed_urls"][url] = {
            "processed_at": datetime.now().isoformat(),
            "info": paper_info
        }
        self.save_state()
    
    def get_file_hash(self, filepath: str) -> str:
        """获取文件内容hash"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return hashlib.md5(f.read().encode()).hexdigest()
    
    def has_file_changed(self, filepath: str) -> bool:
        """检查文件是否有变化"""
        current_hash = self.get_file_hash(filepath)
        old_hash = self.state["file_hashes"].get(filepath)
        return current_hash != old_hash
    
    def update_file_hash(self, filepath: str):
        """更新文件hash"""
        self.state["file_hashes"][filepath] = self.get_file_hash(filepath)
        self.save_state()


# ==================== Markdown处理器 ====================
class MarkdownProcessor:
    """处理Markdown文件"""
    
    def __init__(self, state_manager: StateManager, pdf_dir: str):
        self.state = state_manager
        self.pdf_dir = pdf_dir
    
    def process_file(self, filepath: str) -> List[Tuple[str, PaperInfo, str]]:
        """
        处理Markdown文件，返回新处理的论文列表
        Returns: [(原始URL, PaperInfo, 本地PDF路径), ...]
        """
        results = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 提取所有URL
        urls = URLParser.find_urls_in_text(content)
        
        for url in urls:
            if self.state.is_url_processed(url):
                continue
            
            print(f"\n  发现新链接: {url}")
            
            # 尝试解析arXiv ID
            arxiv_id = URLParser.extract_arxiv_id(url)
            if arxiv_id:
                paper_info = self._process_arxiv(arxiv_id)
                if paper_info:
                    # 下载PDF
                    pdf_filename = PDFDownloader.generate_filename(paper_info)
                    pdf_path = os.path.join(self.pdf_dir, pdf_filename)
                    
                    if PDFDownloader.download(paper_info.pdf_url, pdf_path):
                        print(f"  ✓ PDF已下载: {pdf_filename}")
                        relative_pdf_path = os.path.relpath(pdf_path, os.path.dirname(filepath))
                    else:
                        relative_pdf_path = None
                    
                    results.append((url, paper_info, relative_pdf_path))
                    
                    # 标记为已处理
                    self.state.mark_url_processed(url, {
                        "title": paper_info.title,
                        "arxiv_id": arxiv_id
                    })
                    
                    # 处理多个链接时添加延迟，避免API限速
                    time.sleep(2)
                continue
            
            # 尝试解析DOI (基础支持)
            doi = URLParser.extract_doi(url)
            if doi:
                print(f"  [信息] 检测到DOI: {doi}，暂时仅支持arXiv链接的完整处理")
                self.state.mark_url_processed(url, {"doi": doi})
        
        return results
    
    def _process_arxiv(self, arxiv_id: str) -> Optional[PaperInfo]:
        """处理arXiv论文 - 优先使用Semantic Scholar API"""
        print(f"  正在获取论文信息: {arxiv_id}")
        
        # 优先使用Semantic Scholar（更稳定，且包含引用数）
        paper_info = SemanticScholarAPI.get_full_paper_info(arxiv_id)
        
        # 如果Semantic Scholar失败，尝试arXiv API
        if not paper_info:
            print(f"  [信息] 尝试使用arXiv API...")
            paper_info = ArxivAPI.get_paper_info(arxiv_id)
        
        if not paper_info:
            print(f"  [错误] 无法获取论文信息")
            return None
        
        print(f"  ✓ 标题: {paper_info.title[:60]}...")
        print(f"  ✓ 作者: {paper_info.format_authors()}")
        
        # 如果引用数还没有，单独获取（加延迟避免限速）
        if paper_info.citations is None:
            print(f"  正在获取引用数...")
            time.sleep(1)  # 避免连续请求被限速
            citations = SemanticScholarAPI.get_citations(arxiv_id=arxiv_id)
            if citations is not None:
                paper_info.citations = citations
        
        if paper_info.citations is not None:
            print(f"  ✓ 引用数: {paper_info.citations}")
        else:
            print(f"  [警告] 无法获取引用数")
        
        return paper_info
    
    def update_file_with_formatted_refs(self, filepath: str, 
                                        results: List[Tuple[str, PaperInfo, str]]):
        """更新文件，在原始URL后面追加格式化的引用信息"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for url, paper_info, pdf_path in results:
            formatted = paper_info.to_markdown(pdf_path)
            
            # 在URL后面追加格式化信息
            # 使用字符串替换而非正则，避免特殊字符问题
            # 查找独立的URL行（URL单独一行）
            lines = content.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                # 如果这一行就是URL（去除首尾空白后匹配）
                if line.strip() == url:
                    new_lines.append('')  # 空行
                    new_lines.append(formatted)
            content = '\n'.join(new_lines)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✓ 已更新文件: {filepath}")


# ==================== 文件监控 ====================
class PaperWatcherHandler(FileSystemEventHandler):
    """文件变化处理器"""
    
    def __init__(self, processor: MarkdownProcessor, state: StateManager):
        self.processor = processor
        self.state = state
        self.pending_files = set()
        self.last_event_time = {}
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        if not event.src_path.endswith('.md'):
            return
        
        # 防抖：同一文件2秒内只处理一次
        current_time = time.time()
        last_time = self.last_event_time.get(event.src_path, 0)
        if current_time - last_time < 2:
            return
        
        self.last_event_time[event.src_path] = current_time
        self.pending_files.add(event.src_path)
    
    def process_pending(self):
        """处理待处理的文件"""
        for filepath in list(self.pending_files):
            if not os.path.exists(filepath):
                self.pending_files.discard(filepath)
                continue
            
            print(f"\n{'='*50}")
            print(f"检测到文件变化: {filepath}")
            
            try:
                results = self.processor.process_file(filepath)
                
                if results:
                    print(f"\n处理了 {len(results)} 篇新论文:")
                    for url, paper_info, pdf_path in results:
                        print(f"\n  📄 {paper_info.title[:50]}...")
                        print(f"     {paper_info.to_markdown(pdf_path)}")
                    
                    # 询问是否更新文件
                    self.processor.update_file_with_formatted_refs(filepath, results)
                else:
                    print("  没有发现新的论文链接")
                
                self.state.update_file_hash(filepath)
            except Exception as e:
                print(f"  [错误] 处理文件失败: {e}")
            
            self.pending_files.discard(filepath)


# ==================== 主程序 ====================
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='论文笔记自动化工具')
    parser.add_argument('--watch', '-w', type=str, default='./papers',
                        help='监控的目录 (默认: ./papers)')
    parser.add_argument('--pdf-dir', '-p', type=str, default=None,
                        help='PDF保存目录 (默认: 监控目录/pdfs)')
    parser.add_argument('--once', '-o', action='store_true',
                        help='只扫描一次，不持续监控')
    parser.add_argument('--proxy', type=str, default=None,
                        help='代理地址 (例如: http://127.0.0.1:7897)')
    parser.add_argument('--no-proxy', action='store_true',
                        help='禁用代理')
    
    args = parser.parse_args()
    
    # 处理代理配置
    if args.no_proxy:
        CONFIG["use_proxy"] = False
    elif args.proxy:
        CONFIG["use_proxy"] = True
        CONFIG["proxy"] = {
            "http": args.proxy,
            "https": args.proxy
        }
    
    watch_dir = os.path.abspath(args.watch)
    pdf_dir = args.pdf_dir or os.path.join(watch_dir, 'pdfs')
    state_file = os.path.join(watch_dir, '.paper_watcher_state.json')
    
    # 确保目录存在
    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)
    
    proxy_status = "已启用" if CONFIG["use_proxy"] else "已禁用"
    proxy_addr = CONFIG.get("proxy", {}).get("http", "N/A") if CONFIG["use_proxy"] else "N/A"
    
    print(f"""
╔══════════════════════════════════════════════════════╗
║           📚 论文笔记自动化工具 v1.1                   ║
╠══════════════════════════════════════════════════════╣
║  监控目录: {watch_dir:<40} ║
║  PDF目录:  {pdf_dir:<40} ║
║  代理状态: {proxy_status:<40} ║
║  代理地址: {proxy_addr:<40} ║
╚══════════════════════════════════════════════════════╝
""")
    
    # 初始化组件
    state = StateManager(state_file)
    processor = MarkdownProcessor(state, pdf_dir)
    
    if args.once:
        # 单次扫描模式
        print("单次扫描模式...")
        for filename in os.listdir(watch_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(watch_dir, filename)
                print(f"\n处理文件: {filename}")
                results = processor.process_file(filepath)
                if results:
                    processor.update_file_with_formatted_refs(filepath, results)
        print("\n扫描完成！")
        return
    
    # 持续监控模式
    handler = PaperWatcherHandler(processor, state)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    
    print("开始监控... (按 Ctrl+C 停止)")
    print("提示: 在Markdown文件中添加arXiv链接，保存后会自动处理\n")
    
    try:
        while True:
            time.sleep(1)
            handler.process_pending()
    except KeyboardInterrupt:
        print("\n停止监控...")
        observer.stop()
    
    observer.join()
    print("已退出")


if __name__ == '__main__':
    main()

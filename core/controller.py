from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

class ScraperController:
    def __init__(self):
        # 設定共用的 headless option
        self.options = webdriver.ChromeOptions()
        self.options.add_argument("--headless")
        self.options.add_argument("--disable-gpu")
        self.options.add_argument("--window-size=1920,1080")

    def fetch_holdings(self, etf_code):
        """根據不同 ETF 呼叫對應的爬蟲函式"""
        if etf_code == "00981A":
            return self._fetch_00981a()
        elif etf_code == "00991A":
            return self._fetch_00991a()
        elif etf_code == "00988A":
            return self._fetch_00988a()
        elif etf_code == "00980A":
            return self._fetch_nomura_etf("00980A", "https://www.nomurafunds.com.tw/ETFWEB/product-description?fundNo=00980A&tab=Shareholding")
        elif etf_code == "00985A":
            return self._fetch_nomura_etf("00985A", "https://www.nomurafunds.com.tw/ETFWEB/product-description?fundNo=00985A&tab=Shareholding")
        elif etf_code == "00982A":
            return self._fetch_capital_etf("00982A", "https://www.capitalfund.com.tw/etf/product/detail/399/portfolio")
        elif etf_code == "00992A":
            return self._fetch_capital_etf("00992A", "https://www.capitalfund.com.tw/etf/product/detail/500/portfolio")
        elif etf_code in ["00986A", "00987A"]:
            return self._fetch_tsit_etf(etf_code)
        elif etf_code == "00993A":
            return self._fetch_allianz_etf(etf_code, "https://etf.allianzgi.com.tw/etf-info/E0002?tab=4")
        else:
            print(f"尚未支援爬取 {etf_code}")
            return None

    def _fetch_00981a(self):
        url = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW"
        print(f"啟動 Selenium 爬取 00981A: {url}")
        driver = webdriver.Chrome(options=self.options)
        holdings = {}
        
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
            time.sleep(3)
            
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 4:
                    stock_code = cols[0].get_attribute('textContent').strip()
                    stock_name = cols[1].get_attribute('textContent').strip()
                    shares_str = cols[2].get_attribute('textContent').strip().replace(',', '')
                    weight_str = cols[3].get_attribute('textContent').strip().replace('%', '')
                    
                    if stock_code.isdigit() and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 00981A 失敗: {e}")
        finally:
            driver.quit()
        return holdings

    def _fetch_00988a(self):
        url = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=61YTW"
        print(f"啟動 Selenium 爬取 00988A: {url}")
        driver = webdriver.Chrome(options=self.options)
        holdings = {}
        
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
            time.sleep(3)
            
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 4:
                    stock_code = cols[0].get_attribute('textContent').strip()
                    stock_name = cols[1].get_attribute('textContent').strip()
                    shares_str = cols[2].get_attribute('textContent').strip().replace(',', '')
                    weight_str = cols[3].get_attribute('textContent').strip().replace('%', '')
                    
                    # 海外股票代碼不一定是純數字，所以放寬檢查條件，只要股數與權重是數字即認列
                    # 避免抓到淨值表格的日期 (例: 115/01/27)，加上不包含 '/' 的判斷
                    if stock_code and '/' not in stock_code and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 00988A 失敗: {e}")
        finally:
            driver.quit()
        return holdings

    def _fetch_00991a(self):
        url = "https://www.fhtrust.com.tw/ETF/etf_detail/ETF23#stockhold"
        print(f"啟動 Selenium 爬取 00991A: {url}")
        driver = webdriver.Chrome(options=self.options)
        holdings = {}

        try:
            driver.get(url)
            time.sleep(3)

            # 點擊「基金資產」tab
            tabs = driver.find_elements(By.XPATH, "//a[contains(text(), '基金資產')]")
            if tabs:
                driver.execute_script('arguments[0].click();', tabs[0])
                time.sleep(3)

            # 一直點「展開更多」直到全部讀完
            while True:
                more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '展開更多')]")
                if more_btns and more_btns[0].is_displayed():
                    driver.execute_script('arguments[0].click();', more_btns[0])
                    time.sleep(2)  # 等待新資料載入
                else:
                    break

            # 抓取表格
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                # 00991A 欄位: 證券代號, 證券名稱, 股數, 金額, 權重(%)
                if len(cols) >= 5:
                    stock_code = cols[0].get_attribute('textContent').strip()
                    stock_name = cols[1].get_attribute('textContent').strip()
                    shares_str = cols[2].get_attribute('textContent').strip().replace(',', '')
                    weight_str = cols[4].get_attribute('textContent').strip().replace('%', '')

                    if stock_code.isdigit() and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 00991A 失敗: {e}")
        finally:
            driver.quit()
            
        return holdings

    def _fetch_nomura_etf(self, etf_code, url):
        print(f"啟動 Selenium 爬取 {etf_code}: {url}")
        driver = webdriver.Chrome(options=self.options)
        holdings = {}

        try:
            driver.get(url)
            time.sleep(3)

            while True:
                more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '查看更多')]")
                clicked = False
                for btn in more_btns:
                    if btn.is_displayed():
                        driver.execute_script('arguments[0].click();', btn)
                        clicked = True
                        time.sleep(2)
                        break
                if not clicked:
                    break

            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 4:
                    stock_code = cols[0].get_attribute('textContent').strip()
                    stock_name = cols[1].get_attribute('textContent').strip()
                    shares_str = cols[2].get_attribute('textContent').strip().replace(',', '')
                    weight_str = cols[3].get_attribute('textContent').strip().replace('%', '')

                    if stock_code.isdigit() and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 {etf_code} 失敗: {e}")
        finally:
            driver.quit()
            
        return holdings

    def _fetch_capital_etf(self, etf_code, url):
        print(f"啟動實體瀏覽器爬取 {etf_code} (為繞過網站防爬蟲機制，將會短暫閃過瀏覽器畫面): {url}")
        
        # 針對群益系列使用特製的可見瀏覽器搭配 stealth
        options = webdriver.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-gpu')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=options)
        stealth(driver, languages=['en-US', 'en'], vendor='Google Inc.', platform='Win32', webgl_vendor='Intel Inc.', renderer='Intel Iris OpenGL Engine', fix_hairline=True)
        
        holdings = {}

        try:
            driver.get(url)
            time.sleep(8)
            
            # 如果有展開全部
            more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '展開全部')]")
            if more_btns and more_btns[0].is_displayed():
                driver.execute_script('arguments[0].click();', more_btns[0])
                time.sleep(2)

            rows = driver.find_elements(By.CSS_SELECTOR, ".tr")
            for r in rows:
                text = r.get_attribute('textContent')
                if not text: continue
                
                parts = text.split()
                if len(parts) >= 4 and parts[0].isdigit():
                    stock_code = parts[0]
                    stock_name = parts[1]
                    weight_str = parts[-2].replace('%', '') # 取倒數第二個元素 (防名字有空白)
                    shares_str = parts[-1].replace(',', '') # 取最後一個元素

                    if shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 {etf_code} 失敗: {e}")
        finally:
            driver.quit()
            
        return holdings

    def _fetch_tsit_etf(self, etf_code):
        url = f"https://www.tsit.com.tw/ETF/Home/ETFSeriesDetail/{etf_code}"
        print(f"啟動 Selenium 爬取 {etf_code}: {url}")
        driver = webdriver.Chrome(options=self.options)
        holdings = {}
        
        try:
            driver.get(url)
            time.sleep(8)
            
            rows = driver.find_elements(By.CSS_SELECTOR, "tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 4:
                    texts = [c.get_attribute('textContent').strip() for c in cols]
                    
                    stock_code = texts[0].split()[0] if texts[0] else ""
                    stock_name = texts[1]
                    
                    if stock_code.isdigit() and len(texts) >= 5: 
                        stock_code = texts[1].split()[0] if texts[1] else ""
                        stock_name = texts[2]
                        shares_str = texts[3].replace(',', '')
                        weight_str = texts[4].replace('%', '')
                    else:
                        shares_str = texts[2].replace(',', '') if len(texts)>2 else ""
                        weight_str = texts[3].replace('%', '') if len(texts)>3 else ""
                        
                    if stock_code and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 {etf_code} 失敗: {e}")
        finally:
            driver.quit()
            
        return holdings

    def _fetch_allianz_etf(self, etf_code, url):
        print(f"啟動 Selenium 爬取 {etf_code}: {url}")
        
        options = webdriver.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--headless')
        
        driver = webdriver.Chrome(options=options)
        holdings = {}
        
        try:
            driver.get(url)
            time.sleep(5)
            
            rows = driver.find_elements(By.CSS_SELECTOR, '.content-wrap table tbody tr')
            if not rows:
                rows = driver.find_elements(By.CSS_SELECTOR, 'table tbody tr')
                
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, 'td')
                if len(cols) >= 5:
                    stock_code = cols[1].text.strip()
                    stock_name = cols[2].text.strip()
                    shares_str = cols[3].text.replace(',', '').strip()
                    weight_str = cols[4].text.replace('%', '').strip()
                    
                    if stock_code.isdigit() and shares_str.replace('.', '', 1).isdigit() and weight_str.replace('.', '', 1).isdigit():
                        holdings[stock_code] = {
                            "name": stock_name,
                            "shares": int(float(shares_str)),
                            "weight": float(weight_str)
                        }
        except Exception as e:
            print(f"爬取 {etf_code} 失敗: {e}")
        finally:
            driver.quit()
            
        return holdings

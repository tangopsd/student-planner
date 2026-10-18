import type { Metadata } from "next";
import { DM_Sans, Fraunces, Newsreader, Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
});

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["300", "400"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "Quill",
  description: "Deadlines grouped by the week they fall in.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${outfit.variable} ${newsreader.variable} ${dmSans.variable} ${fraunces.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){function strip(node){if(!node||node.nodeType!==1)return;if(node.hasAttribute&&node.hasAttribute('fdprocessedid'))node.removeAttribute('fdprocessedid');var found=node.querySelectorAll&&node.querySelectorAll('[fdprocessedid]');if(found)for(var i=0;i<found.length;i++)found[i].removeAttribute('fdprocessedid');}var root=document.documentElement;new MutationObserver(function(records){for(var i=0;i<records.length;i++){var record=records[i];if(record.type==='attributes'&&record.target&&record.target.removeAttribute)record.target.removeAttribute('fdprocessedid');var added=record.addedNodes;for(var j=0;j<added.length;j++)strip(added[j]);}}).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['fdprocessedid']});strip(root);})();",
          }}
        />
        {children}
      </body>
    </html>
  );
}

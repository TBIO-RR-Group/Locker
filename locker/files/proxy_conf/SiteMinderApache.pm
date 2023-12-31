#file:SiteMinderApache.pm
#--------------------------
  package SiteMinderApache;
  
  use strict;
  use warnings;
  use Data::Dumper;
  use LWP::UserAgent;
  use Cache::FastMmap;

  use APR::Table ();  
  use Apache2::RequestRec ();
  use Apache2::Connection ();
  use Apache2::RequestUtil ();
  
  use Apache2::Const -compile => qw(FORBIDDEN OK REDIRECT);

  use constant SHARE_FILE => '/tmp/.cache_fastmmap_sharefile';

  our $requiredUsers = {};
  my $ssoParams = {};
  while (my $curLine = <DATA>) {      
      $curLine = rem_ws($curLine);
      next if ($curLine =~ m/^\#/);
      my @lineParts = split /\t/, $curLine;
      if (scalar @lineParts <= 1) {
	  $requiredUsers->{$lineParts[0]} = 1;
      } else {
	  $ssoParams->{$lineParts[0]} = $lineParts[1];
      }
  }

  my $SSO_SESSION_COOKIE_NAME = $ssoParams->{'SSO_SESSION_COOKIE_NAME'};
  my $REDIRECT_TARGET_ARGNAME = $ssoParams->{'REDIRECT_TARGET_ARGNAME'};

  our $validatedCookies = Cache::FastMmap->new('share_file' => SHARE_FILE);
  
  sub handler {
      my $r = shift;

      my $cookies = $r->headers_in()->{Cookie};
      my $cookies_hashref = parseCookies($cookies);

      my $hostport = join ':', $r->get_server_name, $r->get_server_port;
      my $full_url = "http://" . $hostport . $r->unparsed_uri();
      my $location =  $ssoParams->{'REDIRECT_URL'} . "?${REDIRECT_TARGET_ARGNAME}=" . uri_encode($full_url);

      if (!defined($cookies_hashref->{$SSO_SESSION_COOKIE_NAME})) {
#logit("No $SSO_SESSION_COOKIE_NAME, redirecting\n");
         $r->headers_out->set(Location => $location);
         return Apache2::Const::REDIRECT;
      }

      removeInvalidCookies();

      my $validatedCookieVals = $validatedCookies->get($cookies_hashref->{$SSO_SESSION_COOKIE_NAME});
      if (defined($validatedCookieVals)) {
	  if ($requiredUsers->{$validatedCookieVals->[2]}) {
	      return Apache2::Const::OK;
	  } else {
#	      logit("Forbidden1\n");
	      return Apache2::Const::FORBIDDEN;
	  }
      }

      my $pass = 0;

      my $ua = LWP::UserAgent->new();
      my $res = $ua->get($ssoParams->{'VALIDATE_URL'}, "Cookie" => "${SSO_SESSION_COOKIE_NAME}=" . $cookies_hashref->{$SSO_SESSION_COOKIE_NAME} );
      if ($res->is_success()) {
	  my $resContent = $res->content;
	  if (empty($resContent)) { $resContent = "" }
	  my @resLines = map { rem_ws($_); } split /\n/, $resContent;
	  if ((scalar @resLines <= 0) || ($resLines[0] ne 'Success')) {
#logit("did not validate, redirecting\n");
#logit(Dumper(\@resLines) . "\n");
#logit($res->content . "\n");
             $r->headers_out->set(Location => $location);
             return Apache2::Const::REDIRECT;
	  }
	  my $validateVals = {};
	  map { if (m/^([^\=]+)\=(.+)$/) { $validateVals->{$1} = $2; } } @resLines;
	  if ($requiredUsers->{$validateVals->{'User'}}) {
	      $pass = 1;
	      $validatedCookies->set($cookies_hashref->{$SSO_SESSION_COOKIE_NAME},[$validateVals->{"TTL"},time(),$validateVals->{"User"}]);
#	      logit("Added new SM Cookie:\n" . $cookies_hashref->{$SSO_SESSION_COOKIE_NAME} . "\n" . $validateVals->{"TTL"}. "\n" . $validateVals->{"User"} . "\n");
	  }
      }

#logit("pass = $pass\n");  
      return $pass
          ? Apache2::Const::OK
          : Apache2::Const::FORBIDDEN;
  }

  #Got from here (orig called urlize): http://code.activestate.com/recipes/577450-perl-url-encode-and-decode/
  sub uri_encode {
      my ($rv) = @_;
      $rv =~ s/([^A-Za-z0-9])/sprintf("%%%2.2X", ord($1))/ge;
      return $rv;
  }

  sub removeInvalidCookies {

      my $currentEpochSecs = time();
      my @allSmsessionArr = $validatedCookies->get_keys();
#      logit("Before NUM KEYS: " . scalar(@allSmsessionArr) . "\n");
      foreach my $smsessionCookie (@allSmsessionArr) {
	  my $cookieTimeVals = $validatedCookies->get($smsessionCookie);
	  if (!defined($cookieTimeVals) || (scalar @$cookieTimeVals < 3)) { $validatedCookies->remove($smsessionCookie); }
	  my ($initTtlSecs, $initEpochSecs) = @$cookieTimeVals;
	  my $secsDiff = $currentEpochSecs - $initEpochSecs;
	  my $remainingTtlSecs = $initTtlSecs - $secsDiff;
	  if ($remainingTtlSecs <= 0) { $validatedCookies->remove($smsessionCookie); }
      }
      @allSmsessionArr = $validatedCookies->get_keys();
#      logit("After NUM KEYS: " . scalar(@allSmsessionArr) . "\n");

  }


  sub logit {
	
     my ($msg) = @_;

     open F, ">>/tmp/AKSlog.txt";
     print F "PROC $$ : $msg";
     close(F);
}


#Or could use:
#      use Cookie::Baker;
#      my $cookies_hashref = crush_cookie($r->headers_in()->{Cookie});
  sub parseCookies {

      my ($cookies) = @_;

      if (empty($cookies)) { $cookies = ""; }

      my $cookiesHash = {};
      my @cookiesSplit = split /\s*;\s*/, $cookies;
      foreach my $curCookie (@cookiesSplit) {
	  if ($curCookie =~ m/^(.+)=(.+)$/i) {
	      my $cname = $1;
	      my $cvalue = $2;
	      $cname = rem_ws($cname);
	      $cvalue = rem_ws($cvalue);
	      $cookiesHash->{$cname} = $cvalue;
	  }
      }
      return($cookiesHash);
  }

  sub rem_ws {
      my ($inVal) = @_;

      if (!defined($inVal)) { return(""); }
      $inVal =~ s/^\s+//;
      $inVal =~ s/\s+$//;
      return($inVal);
}

  sub empty {
      my ($inVal) = @_;

      if (!defined($inVal)) { return(1); }
      if ($inVal =~ m/^\s*$/) { return(1); }
      return(0);
}
  
1;

###Add __DATA__ section at bottom listing users who can access, e.g.:
#__DATA__
#smitha26
#russom
#rens
